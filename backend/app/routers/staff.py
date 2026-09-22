# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

# [修复 2026-09-01] 添加 Request 导入，用于获取客户端 IP 地址记录到系统日志
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user, require_permission,
    get_user_department_scope, get_user_work_type_scope, has_department_access, can_access_staff,
    ROLE_EMPLOYEE,
    ROLE_DEPT_MANAGER,
    has_permission, has_any_permission,
    PERM_STAFF_VIEW, PERM_STAFF_CREATE, PERM_STAFF_EDIT, PERM_STAFF_DELETE, PERM_STAFF_STATUS,
    PERM_STAFF_VIEW_RESIGNED,
)
from app.models.user import User
from app.models.department import Department
from app.schemas.staff import (
    StaffCreate, StaffUpdate, StaffResponse, StaffListResponse,
    WORK_TYPES, WORK_TYPE_DOCTOR, WORK_TYPE_NURSE,
    WORK_TYPE_TECHNICIAN, WORK_TYPE_ADMIN,
    # [新增 2026-09-15] 通知文案需要把工种代码转成可读名称（doctor → 医生）
    WORK_TYPE_LABELS,
)
from app.services.staff_service import (
    get_staff_list, get_resigned_staff_list, get_staff,
    create_staff, update_staff, delete_staff,
)
from app.services.user_service import create_user, get_user
from app.services.audit_service import record_modification, build_change_summary
from app.services.modification_notify import notify_super_admins
# [新增 2026-09-11] 人员信息变更审核：立即生效 + 追认/回滚（字段分级见 staff_change_service）
from app.models.staff_change import SOURCE_ADMIN
from app.services.staff_change_service import DEFERRED_FIELDS, submit_change
from app.schemas.user import UserCreate
from app.utils import utc_now, get_client_ip
from app.constants import WORK_TYPE_TO_USER_TYPE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/staff", tags=["人员管理"])

# 字段显示名称（用于审计日志）
STAFF_FIELD_LABELS = {
    "name": "姓名", "work_type": "工种", "education": "学历", "title": "职称",
    "department": "所属部门", "position": "职务",
    "expertise_short": "专业擅长（短）", "expertise_standard": "专业擅长（标准）",
    "front_photo": "正面照", "side_photo": "侧面照",
    "social_appointments": "社会任职", "honors": "获得荣誉", "remarks": "备注",
}

# 工种到部门类别的映射
WORK_TYPE_DEPT_CATEGORY = {
    WORK_TYPE_DOCTOR: "临床专科",
    WORK_TYPE_TECHNICIAN: "临床专科",
    WORK_TYPE_NURSE: "护理病区",
    WORK_TYPE_ADMIN: "行政科室",
}


def _check_staff_edit_access(user: User, work_type: str, department: str, db: Session) -> bool:
    """检查用户是否有编辑指定人员的权限（权限点 + 数据范围，admin_manager 自动通过）"""
    if not has_permission(user, PERM_STAFF_EDIT):
        return False
    return can_access_staff(user, work_type, department, db)


def _check_staff_create_access(user: User, work_type: str, department: str, db: Session) -> bool:
    """检查用户是否有新增人员的权限（admin_manager 自动通过）"""
    if not has_permission(user, PERM_STAFF_CREATE):
        return False
    if not has_department_access(user, department, db):
        return False
    work_types = get_user_work_type_scope(user)
    if work_types and work_type not in work_types:
        return False
    return True


def _check_staff_delete_access(user: User, work_type: str, department: str, db: Session) -> bool:
    """检查用户是否有删除人员的权限（admin_manager 自动通过）"""
    if not has_permission(user, PERM_STAFF_DELETE):
        return False
    return can_access_staff(user, work_type, department, db)


def _attach_pending(db: Session, items: list) -> list[StaffResponse]:
    """[新增 2026-09-11] 给人员列表附加「待审核变更」提示（一次批量查询，避免 N+1）"""
    from app.services import staff_change_service

    pending = staff_change_service.pending_map(db, [s.employee_id for s in items])
    out: list[StaffResponse] = []
    for s in items:
        resp = StaffResponse.model_validate(s)
        badge = staff_change_service.pending_badge(db, pending.get(s.employee_id, []))
        if badge:
            resp = resp.model_copy(update={"pending_change": badge})
        out.append(resp)
    return out


# ==================== 列表 ====================

@router.get("", response_model=StaffListResponse)
def list_staff(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="搜索工号或姓名"),
    department: str | None = Query(None, description="按部门筛选"),
    work_type: str | None = Query(None, description="按工种筛选: doctor/nurse/technician/admin"),
    status: str | None = Query("active", description="状态筛选: active-在职, resigned-离职"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取人员列表（统一入口）

    权限规则（基于角色配置的权限点 + 数据范围）：
    1. department_scope=all 的角色：可查看所有科室人员
    2. department_scope=managed 的角色：可查看管辖科室的人员
    3. department_scope=own 的角色：仅能查看本科室人员
    4. work_type_scope 限制可见的工种
    """
    # 检查基础查看权限
    if not has_permission(current_user, PERM_STAFF_VIEW):
        return StaffListResponse(total=0, items=[], page=page, page_size=page_size)

    # [修复 2026-09-11] 离职人员越权：本接口原先只校验 staff.view，
    # 传 status=resigned 即可绕过「离职人员」页面的 staff.view_resigned 门禁拿到离职名单。
    # 现要求查询离职状态时必须额外具备 staff.view_resigned。
    if status == "resigned" and not has_permission(current_user, PERM_STAFF_VIEW_RESIGNED):
        raise HTTPException(status_code=403, detail="无权查看离职人员")

    department_filter = None
    is_all_scope = False  # [改进] 标记是否为全院权限，scope=all 时不按部门名过滤，避免 staff.department 值不在 departments 表中被误排除

    # 基于 department_scope 获取可访问的科室（admin_manager 的 scope="all" 自动返回全部）
    # [重构 2026-09-21 / 代码质量审计 Q-6] 科室范围过滤统一走公共函数
    # resolve_department_filter（原为四处各写一遍的复制粘贴逻辑）。
    from app.dependencies import _get_role_dept_scope, resolve_department_filter

    scope = _get_role_dept_scope(current_user)
    allowed_dept_names: list[str] = []

    if scope == "all":
        # [改进] scope=all 时仅做权限校验，不设置 department_filter
        # 原因：staff.department 是自由文本字段，可能包含 departments 表中不存在的值（如"普外科/甲乳外科"）或为空，
        # 用 in_ 过滤会遗漏这些人。scope=all 应看到所有人员。
        is_all_scope = True
        department_filter = department if department else None
    else:
        department_filter, is_empty = resolve_department_filter(current_user, db)
        if is_empty:
            return StaffListResponse(total=0, items=[], page=page, page_size=page_size)
        # 此处用的是"用户主动指定科室"的校验：需确认该科室在其范围内。
        # 公共函数返回的是拼接串，故先还原为列表用于校验成员关系。
        allowed_dept_names = (department_filter or "").split("||") if department_filter else []
        if department:
            if department not in allowed_dept_names:
                raise HTTPException(status_code=403, detail="无权访问该科室")
            department_filter = department

    # 工种范围过滤（基于 work_type_scope，scope="all" 时不限制）
    work_type_filter = None
    from app.dependencies import get_user_work_type_scope, _get_role_work_type_scope
    wt_scope = _get_role_work_type_scope(current_user)
    if wt_scope and "all" not in wt_scope:  # [改进] 仅在工种范围有限制时才过滤
        allowed_work_types = get_user_work_type_scope(current_user)
        if allowed_work_types:
            if work_type:
                if work_type not in allowed_work_types:
                    return StaffListResponse(total=0, items=[], page=page, page_size=page_size)
                work_type_filter = work_type
            else:
                work_type_filter = ",".join(allowed_work_types)

    items, total = get_staff_list(
        db, page=page, page_size=page_size, search=search,
        department=department, work_type=work_type,
        department_filter=department_filter, status=status,
        work_type_filter=work_type_filter,
    )
    # [新增 2026-09-11] 附带「待审核变更」提示（列表卡片上显著位置提示未审核）
    return StaffListResponse(
        total=total, items=_attach_pending(db, items), page=page, page_size=page_size,
    )


@router.get("/resigned", response_model=StaffListResponse)
def list_resigned_staff(
   page: int = Query(1, ge=1),
   page_size: int = Query(20, ge=1, le=100),
   search: str | None = Query(None),
   work_type: str | None = Query(None),
   # [新增 2026-09-11] 保留期视图：active 在档（默认）/ archived 已满保留期仅统计 / all 全部
   scope: str = Query("active", description="active 在档离职人员 / archived 已满保留期 / all 全部"),
   current_user: User = Depends(require_permission(PERM_STAFF_VIEW_RESIGNED)),
   db: Session = Depends(get_db),
):
   """获取离职人员列表（原「员工休息区」，现更名「离职人员」）"""
   # 数据范围过滤（基于 department_scope）
   # [重构 2026-09-21 / 代码质量审计 Q-6] 统一走公共函数 resolve_department_filter
   # 注意：局部变量名不得用 scope，会覆盖上方的保留期视图查询参数（scope）
   from app.dependencies import resolve_department_filter
   department_filter, is_empty = resolve_department_filter(current_user, db)
   if is_empty:
       return StaffListResponse(total=0, items=[], page=page, page_size=page_size)
   
   # 工种范围过滤（基于 work_type_scope）
   work_type_filter = None
   allowed_work_types = get_user_work_type_scope(current_user)
   if allowed_work_types:
       if work_type:
           if work_type not in allowed_work_types:
               return StaffListResponse(total=0, items=[], page=page, page_size=page_size)
           work_type_filter = work_type
       else:
           work_type_filter = ",".join(allowed_work_types)
   
   items, total, stats = get_resigned_staff_list(
       db, page=page, page_size=page_size, search=search, work_type=work_type,
       department_filter=department_filter, work_type_filter=work_type_filter,
       scope=scope,
       )
   return StaffListResponse(
       total=total, items=items, page=page, page_size=page_size, stats=stats,
   )


@router.get("/department-category")
def get_department_category(
    work_type: str = Query(..., description="工种"),
    # [修复 2026-09-17] 补登录校验：原实现无任何 Depends，未认证即可访问
    # （仅返回静态「工种→部门类别」映射，无业务数据，风险低，但不应对外暴露）
    current_user: User = Depends(get_current_user),
):
    """根据工种获取对应的部门类别"""
    if work_type not in WORK_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的工种: {work_type}，有效值: {WORK_TYPES}")
    return {"category": WORK_TYPE_DEPT_CATEGORY.get(work_type, "行政科室")}


# ==================== 详情 ====================

@router.get("/{employee_id}", response_model=StaffResponse)
def get_staff_detail(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取人员详情
    
    所有登录用户可通过此接口查看人员详情（列表已按数据范围过滤）
    """
    staff = get_staff(db, employee_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")
    
    if not has_permission(current_user, PERM_STAFF_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")

    # 数据范围校验：本人可查看自己；他人需在其数据范围内（防跨科室 PHI 泄露）
    if employee_id != current_user.employee_id:
        if not can_access_staff(current_user, staff.work_type, staff.department, db):
            raise HTTPException(status_code=403, detail="无权查看该人员信息")

    # [新增 2026-09-11] 详情页显著位置提示「待 XX 审核」（含审核人可见的通过/驳回入口）
    from app.services import staff_change_service
    pending = staff_change_service.pending_map(db, [staff.employee_id]).get(staff.employee_id, [])
    resp = StaffResponse.model_validate(staff)
    badge = staff_change_service.pending_badge(db, pending)
    return resp.model_copy(update={"pending_change": badge}) if badge else resp


# ==================== 新增 ====================

@router.post("", response_model=StaffResponse, status_code=201)
def create_staff_endpoint(
    staff_in: StaffCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增人员

    权限规则（基于角色的权限点 + 数据范围）：
    需要 staff.create 权限，且目标科室和工种在数据范围内
    """
    # 验证工种
    if staff_in.work_type not in WORK_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的工种: {staff_in.work_type}，有效值: {WORK_TYPES}")

    # 权限+范围检查
    if not _check_staff_create_access(current_user, staff_in.work_type, staff_in.department, db):
        raise HTTPException(status_code=403, detail="权限不足，无法新增该科室的该工种人员")

    # [修复 2026-09-01] 修改工种-科室校验逻辑：优先检查 allowed_work_types，支持混合科室
    # 如果科室配置了 allowed_work_types，则只允许列表中的工种；否则使用原有类别映射规则
    expected_category = WORK_TYPE_DEPT_CATEGORY.get(staff_in.work_type)
    if expected_category:
        dept = db.query(Department).filter(Department.name == staff_in.department).first()
        if dept:
            if dept.allowed_work_types:
                allowed = [wt.strip() for wt in dept.allowed_work_types.split(',')]
                if staff_in.work_type not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"科室「{staff_in.department}」不允许工种「{staff_in.work_type}」，"
                               f"允许的工种: {dept.allowed_work_types}",
                    )
            elif dept.category != expected_category:
                raise HTTPException(
                    status_code=400,
                    detail=f"工种「{staff_in.work_type}」只能选择「{expected_category}」类别的科室，"
                           f"而「{staff_in.department}」属于「{dept.category}」",
                )

    # 检查工号是否重复
    existing = get_staff(db, staff_in.employee_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"工号 {staff_in.employee_id} 已存在")

    # 自动创建用户账号（如果不存在）
    existing_user = get_user(db, staff_in.employee_id)
    if not existing_user:
        user_type = WORK_TYPE_TO_USER_TYPE.get(staff_in.work_type, "admin_user")
        create_user(
            db,
            UserCreate(
                employee_id=staff_in.employee_id,
                name=staff_in.name,
                role=ROLE_EMPLOYEE,
                department=staff_in.department,
                user_type=user_type,
            ),
        )

    # 检查 staff 记录是否已存在（create_user 可能已自动创建）
    existing_staff = get_staff(db, staff_in.employee_id)
    if existing_staff:
        staff = existing_staff
        # 更新已有 staff 记录
        staff.name = staff_in.name
        staff.work_type = staff_in.work_type
        staff.education = staff_in.education
        staff.title = staff_in.title
        staff.department = staff_in.department
        staff.position = staff_in.position
        staff.expertise_short = staff_in.expertise_short
        staff.expertise_standard = staff_in.expertise_standard
        staff.social_appointments = staff_in.social_appointments
        staff.honors = staff_in.honors
        staff.remarks = staff_in.remarks
        if not staff.status:
            staff.status = "active"  # 仅在缺失时默认在职，避免复活离职人员
        db.flush()
    else:
        staff = create_staff(db, staff_in)
    db.commit()

    # [修复 2026-09-01] 新增人员留痕
    try:
        # [修复/问题24] 统一走 get_client_ip，兼容反向代理，避免记录成代理 IP
        client_ip = get_client_ip(request)
        record_modification(
            db, entity_type="staff", entity_id=staff_in.employee_id,
            modified_by=current_user.employee_id,
            change_summary=f"新增人员: {staff_in.name}({staff_in.employee_id}) 工种={staff_in.work_type} 科室={staff_in.department}",
            ip_address=client_ip,
        )
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    # [新增 2026-09-15] 新增人员此前只写留痕、不产生任何站内信（新人建档无人知悉）。
    # 收件人：超管 + 该人员所属科室的科室管理员（自动排除操作者本人）；
    # 若无人可收（例如系统仅有一个超管账号且正是他本人操作），回落给操作者本人
    # 作为操作回执，保证「改了却查不到」不再发生。
    try:
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="新增人员",
            content=(
                f"{modifier_name} 新增了人员 {staff_in.name}({staff_in.employee_id})，"
                f"工种={WORK_TYPE_LABELS.get(staff_in.work_type, staff_in.work_type)}，"
                f"科室={staff_in.department}"
            ),
            related_type="staff",
            related_id=int(staff_in.employee_id) if staff_in.employee_id.isdigit() else None,
            department=staff_in.department,
            exclude_user_id=current_user.employee_id,
            event_code="staff.created",
            context={
                "操作人": modifier_name,
                "姓名": staff_in.name,
                "工号": staff_in.employee_id,
                "科室": staff_in.department,
                "工种": WORK_TYPE_LABELS.get(staff_in.work_type, staff_in.work_type),
            },
        )
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    return staff


# ==================== 更新 ====================

@router.put("/{employee_id}", response_model=StaffResponse)
def update_staff_endpoint(
    employee_id: str,
    staff_in: StaffUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新人员信息

    隐式权限：所有登录用户可修改自己的信息（无需 staff.edit 权限）
    显式权限：需要 staff.edit 权限 + 数据范围匹配，才能修改他人
    """
    staff = get_staff(db, employee_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")

    # 隐式权限：修改自己（所有登录用户都可以）
    is_self = employee_id == current_user.employee_id
    if is_self:
        pass  # 允许修改自己
    # 显式权限检查：有 staff.edit 权限 + 在数据范围内
    elif not _check_staff_edit_access(current_user, staff.work_type, staff.department, db):
        raise HTTPException(status_code=403, detail="权限不足，无法修改该人员信息")

    # 如果更新了部门，验证与工种的匹配
    update_data = staff_in.model_dump(exclude_unset=True)
    new_department = update_data.get("department", staff.department)
    new_work_type = update_data.get("work_type", staff.work_type)

    # [修复] 本人编辑时也校验 department/work_type 变更在权限范围内：
    # 员工若无 staff.edit 权限或数据范围不匹配，不得修改自己的科室/工种，
    # 防止通过改科室越权获取其他科室数据访问范围
    if is_self and ("department" in update_data or "work_type" in update_data):
        dept_changed = update_data.get("department", staff.department) != staff.department
        work_type_changed = update_data.get("work_type", staff.work_type) != staff.work_type
        if dept_changed or work_type_changed:
            if not _check_staff_edit_access(current_user, new_work_type, new_department, db):
                raise HTTPException(
                    status_code=403,
                    detail="权限不足，无法修改本人科室/工种信息，请联系管理员处理",
                )

    # [修复 2026-09-01] 修改更新人员时的工种-科室校验逻辑：优先检查 allowed_work_types，支持混合科室
    if "department" in update_data or "work_type" in update_data:
        expected_category = WORK_TYPE_DEPT_CATEGORY.get(new_work_type)
        if expected_category:
            dept = db.query(Department).filter(Department.name == new_department).first()
            if dept:
                if dept.allowed_work_types:
                    allowed = [wt.strip() for wt in dept.allowed_work_types.split(',')]
                    if new_work_type not in allowed:
                        raise HTTPException(
                            status_code=400,
                            detail=f"科室「{new_department}」不允许工种「{new_work_type}」，"
                                   f"允许的工种: {dept.allowed_work_types}",
                        )
                elif dept.category != expected_category:
                    raise HTTPException(
                        status_code=400,
                        detail=f"工种「{new_work_type}」只能选择「{expected_category}」类别的科室，"
                               f"而「{new_department}」属于「{dept.category}」",
                    )

    # 记录变更
    old_data = {field: getattr(staff, field) for field in STAFF_FIELD_LABELS.keys()}
    change_summary = build_change_summary(old_data, update_data, STAFF_FIELD_LABELS)

    old_department = staff.department

    # [新增 2026-09-11] 延迟生效字段（科室/工种）本次不落库：
    # 二者决定数据可见范围，若立即生效会出现「先拿到新科室数据权限、后被驳回」的越权窗口，
    # 故登记为变更申请、等审核通过时再由审核服务写入（详见 staff_change_service）。
    apply_in = StaffUpdate(**{
        k: v for k, v in update_data.items() if k not in DEFERRED_FIELDS
    })
    staff = update_staff(db, employee_id, apply_in, updated_by=current_user.employee_id)
    # [修复 2026-09-01] 传递客户端 IP 到 record_modification，记录到系统日志
    client_ip = get_client_ip(request)
    mod_record = record_modification(
        db, entity_type="staff", entity_id=employee_id,
        modified_by=current_user.employee_id, change_summary=change_summary,
        ip_address=client_ip,
    )

    # 同步更新用户表的姓名/科室信息（两处都有存储，避免列表与详情口径不一致）
    if update_data.get("name") or new_department != old_department:
        user = get_user(db, employee_id)
        if user:
            if update_data.get("name"):
                user.name = update_data["name"]
            if new_department != old_department:
                user.department = new_department

    # [新增 2026-09-11] 登记变更审核任务（立即生效 + 追认）：
    # 姓名/科室/工种 → 超管审；学历/职称/职务/照片 → 科室负责人审（无负责人升级超管）；
    # 备注/擅长/荣誉等低风险字段 → 免审。超管提交免审（仅留痕）。
    _change_req, reviewers = submit_change(
        db, staff=staff, before=old_data, payload=update_data,
        submitter=current_user, source=SOURCE_ADMIN,
    )

    # [调整 2026-09-11] 站内信提醒：
    # - 已派发审核任务时，改为「待审核」站内信直达审核人（避免既群发又要审核的重复打扰）；
    # - 免审改动仍沿用原有提醒（收件人 = 超管 + 相关科室管理员，排除操作者本人）。
    # [修复 2026-09-15] 原实现在「已派发审核任务」时**完全不再发提醒**，形成监管空白：
    # 审核人只知道自己被指派了任务，而未参与审核的其他管理者（通常是超管）对
    # 「某个字段已经被改动」一无所知。现补发一条报备通知给「超管 + 相关科室管理员」
    # 中**未担任审核人**的成员（exclude_ids 去重，避免重复打扰审核人）。
    if change_summary and change_summary != "更新操作":
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="人员信息被修改" + ("（已提交审核）" if reviewers else ""),
            content=(
                f"{modifier_name} 修改了 {staff.name}({employee_id}) 的{change_summary}"
                + (f"（已提交审核，待 {len(reviewers)} 位审核人处理）" if reviewers else "")
            ),
            related_type="staff",
            # 站内信详情页据此跳转到人员详情（工号均为 6 位数字）
            related_id=int(employee_id) if employee_id.isdigit() else None,
            department=staff.department,
            exclude_user_id=current_user.employee_id,
            # 审核人已单独收到「待审核」任务通知，此处不重复打扰
            exclude_ids=reviewers or None,
            # [新增 2026-09-15] 接入可配置通知中心（事件：人员信息被修改）
            event_code="staff.updated",
            context={
                "操作人": modifier_name,
                "姓名": staff.name,
                "工号": employee_id,
                "变更内容": change_summary,
            },
        )

    db.commit()
    return staff


# ==================== 删除 ====================

@router.delete("/{employee_id}")
def delete_staff_endpoint(
    employee_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除人员"""
    staff = get_staff(db, employee_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")

    if not _check_staff_delete_access(current_user, staff.work_type, staff.department, db):
        raise HTTPException(status_code=403, detail="权限不足，无法删除")

    # [修复] 删除前收集磁盘照片路径，数据库记录删除后同步清理文件，
    # 避免删除人员后照片文件成为孤儿长期残留占盘
    from app.services.upload_service import delete_file as _delete_upload_file
    photos_to_delete = [p for p in (staff.front_photo, staff.side_photo) if p]

    staff_name = staff.name
    staff_work_type = staff.work_type
    # [新增 2026-09-15] 记录所属科室：删除后的站内信需要用它来解析收件人
    # （超管 + 该科室的科室管理员），删除后再取会触发已删除对象的属性访问错误
    staff_department = staff.department
    success = delete_staff(db, employee_id)
    if not success:
        raise HTTPException(status_code=404, detail="人员不存在")

    # [修复 2026-09-01] 删除人员留痕
    try:
        client_ip = get_client_ip(request)
        record_modification(
            db, entity_type="staff", entity_id=employee_id,
            modified_by=current_user.employee_id,
            change_summary=f"删除人员: {staff_name}({employee_id}) 工种={staff_work_type}",
            ip_address=client_ip,
        )
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    # [新增 2026-09-15] 删除人员此前只写留痕、不产生站内信。删除档案会连带清理
    # 照片文件，属不可逆的高敏感操作，现补上提醒（事件：删除人员）：
    # 收件人 = 超管 + 该人员所属科室的科室管理员（排除操作者本人），
    # 若无人可收则回落给操作者本人作为操作回执。
    try:
        mod_user = get_user(db, current_user.employee_id)
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title="删除人员",
            content=(
                f"{modifier_name} 删除了人员 {staff_name}({employee_id})，"
                f"工种={WORK_TYPE_LABELS.get(staff_work_type, staff_work_type)}，"
                f"科室={staff_department or '未设置'}，其档案与照片文件已被清理"
            ),
            related_type="staff",
            department=staff_department,
            exclude_user_id=current_user.employee_id,
            event_code="staff.deleted",
            context={
                "操作人": modifier_name,
                "姓名": staff_name,
                "工号": employee_id,
                "科室": staff_department or "未设置",
                "工种": WORK_TYPE_LABELS.get(staff_work_type, staff_work_type),
            },
        )
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    db.commit()

    # 删除磁盘照片文件（delete_file 联动清理 thumb_/orig_ 副本）
    for p in photos_to_delete:
        try:
            _delete_upload_file(p)
        except Exception:
            # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
            # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
            logger.warning(
                "旁路操作失败（已忽略，不影响主流程）", exc_info=True
            )
    return {"message": "删除成功"}


# ==================== 状态变更 ====================

@router.put("/{employee_id}/status")
def update_staff_status(
    employee_id: str,
    request: Request,
    status: str = Query(..., description="新状态: active-在职, resigned-离职"),
    # [新增 2026-09-11] 离职原因（办理离职时可选，便于后续核查与统计）
    reason: str | None = Query(None, max_length=200, description="离职原因（可选）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新人员状态（在职/离职）

    [调整 2026-09-11] 离职不再是「只改一个状态」：
    - 记录离职时间（resigned_at）、离职原因（resign_reason）、办理人（resigned_by）；
    - 复职时清空上述离职档案与账号清理提醒标记（account_notice_at）；
    - 状态变更通过**站内信**通知超级管理员 + 相关科室管理员（自动排除操作者本人）。
    """
    staff = get_staff(db, employee_id)
    if not staff:
        raise HTTPException(status_code=404, detail="人员不存在")

    # 权限检查（需要 staff.status 权限 + 数据范围匹配，admin_manager 自动通过）
    if not has_permission(current_user, PERM_STAFF_STATUS):
        raise HTTPException(status_code=403, detail="权限不足")
    if not can_access_staff(current_user, staff.work_type, staff.department, db):
        raise HTTPException(status_code=403, detail="权限不足")

    if status not in ("active", "resigned"):
        raise HTTPException(status_code=400, detail="状态值无效")

    changed = staff.status != status
    staff.status = status
    staff.updated_by = current_user.employee_id
    staff.updated_at = utc_now()

    if status == "resigned":
        # 仅在首次离职时写入离职时间，避免重复点击覆盖真实离职日期；
        # 重复办理离职时允许更新原因
        if not staff.resigned_at:
            staff.resigned_at = utc_now()
        staff.resigned_by = current_user.employee_id
        if reason is not None:
            staff.resign_reason = (reason or "").strip() or None
    else:
        # 复职：清空离职档案与「账号清理」提醒标记，使保留期重新计算
        staff.resigned_at = None
        staff.resign_reason = None
        staff.resigned_by = None
        staff.account_notice_at = None

    # 同步用户账号状态
    user = get_user(db, employee_id)
    if user:
        user.is_active = (status == "active")

    # [修复 2026-09-01] 人员状态变更留痕
    try:
        client_ip = get_client_ip(request)
        status_text = "在职" if status == "active" else "离职"
        record_modification(
            db, entity_type="staff", entity_id=employee_id,
            modified_by=current_user.employee_id,
            change_summary=f"状态变更: → {status_text}",
            ip_address=client_ip,
        )
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )

    # [新增 2026-09-11] 状态变更通过站内信通知：超管 + 相关科室管理员（自动排除操作者本人）。
    # 离职属于敏感操作（会停用登录账号），必须让管理者知悉。
    if changed:
        try:
            operator = get_user(db, current_user.employee_id)
            operator_name = operator.name if operator else current_user.employee_id
            if status == "resigned":
                title = "人员离职提醒"
                extra = f"，原因：{staff.resign_reason}" if staff.resign_reason else ""
                content = (
                    f"{operator_name} 已将 {staff.name}（{employee_id} · {staff.department}）标记为离职"
                    f"{extra}；其登录账号已停用。"
                )
                event_code = "staff.resigned"
                context = {
                    "操作人": operator_name,
                    "姓名": staff.name,
                    "工号": employee_id,
                    "科室": staff.department,
                    "离职原因": extra,
                }
            else:
                title = "人员复职提醒"
                content = (
                    f"{operator_name} 已将 {staff.name}（{employee_id} · {staff.department}）恢复为在职，"
                    f"登录账号已恢复启用。"
                )
                event_code = "staff.restored"
                context = {
                    "操作人": operator_name,
                    "姓名": staff.name,
                    "工号": employee_id,
                    "科室": staff.department,
                }
            notify_super_admins(
                db, title=title, content=content,
                related_type="staff",
                related_id=int(employee_id) if employee_id.isdigit() else None,
                department=staff.department,
                exclude_user_id=current_user.employee_id,
                # [新增 2026-09-15] 接入可配置通知中心（离职 / 复职为两个独立事件，可分别开关）
                event_code=event_code,
                context=context,
            )
        except Exception:
            # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
            # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
            logger.warning(
                "旁路操作失败（已忽略，不影响主流程）", exc_info=True
            )

    db.commit()

    status_text = "在职" if status == "active" else "离职"
    return {"message": f"人员已标记为{status_text}", "status": status}
