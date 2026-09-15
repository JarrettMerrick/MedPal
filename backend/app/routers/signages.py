import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, has_permission, require_any_permission, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_CREATE, PERM_SIGNAGE_EDIT, PERM_SIGNAGE_DELETE, get_user_department_scope, _get_role_dept_scope
from app.models.user import User
from app.models.signage import SignageInspection
from app.schemas.signage import SignageCreate, SignageUpdate, SignageResponse, SignageListResponse, SignagePhotoCreate, SignagePhotoResponse, SignageHistoryResponse, SignageHistoryListResponse
from app.services.signage_service import create_signage, get_signage, get_signage_list, update_signage, delete_signage, create_signage_photo, get_signage_photos, get_signage_history, get_signage_by_code
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：标识被增删改 / 上传附件后通知管理方（此前只留痕不提醒）
from app.services.modification_notify import notify_super_admins
from app.models.department import Department
from app.services.upload_service import save_upload_file, save_signage_design_file, delete_file
# [新增 2026-09-09] 统一 IP 获取（兼容反向代理）
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signages", tags=["标识管理"])


# [新增 2026-09-15] 标识字段中文名与状态/有效期可读化映射（用于站内信变更摘要）
_SIGNAGE_FIELD_LABELS = {
    "name": "名称", "code": "编码", "category": "分类", "category_type": "类别类型",
    "material": "材质", "size_spec": "规格", "status": "状态",
    "campus": "院区", "building": "楼栋", "floor": "楼层", "area": "区域",
    "zone_type": "区域类型", "location_desc": "位置描述",
    "display_text_cn": "中文显示文本", "display_text_en": "英文显示文本",
    "department_id": "关联科室", "validity_type": "有效期类型", "validity_until": "有效期至",
    "install_date": "安装日期", "warranty_expire": "质保到期",
    "manufacturer": "制造商", "vendor_contact": "供应商联系方式",
    "design_photo": "设计文件", "installation_photo": "现场照片", "oa_number": "OA单号",
}
_SIGNAGE_STATUS_LABELS = {
    "normal": "正常", "damaged": "轻微破损",
    "severely_damaged": "严重损坏", "removed": "已拆除",
    "repair_in_progress": "维修处理中",
}
_PHOTO_TYPE_LABELS = {"design": "设计文件", "installation": "现场照片"}


def _fmt_signage_value(field: str, value) -> str:
    """[新增 2026-09-15] 标识字段值可读化：状态/有效期代码转中文，空值显示为「空」"""
    if value is None or value == "":
        return "空"
    if field == "status":
        return _SIGNAGE_STATUS_LABELS.get(str(value), str(value))
    if field == "validity_type":
        return {"long_term": "长期", "temporary": "临时"}.get(str(value), str(value))
    return str(value)


def _photo_type_label(t: str | None) -> str:
    """[新增 2026-09-15] 照片类型可读化：design → 设计文件"""
    return _PHOTO_TYPE_LABELS.get((t or "").strip(), (t or "").strip() or "照片")


def _dept_name_of(s) -> str | None:
    """[新增 2026-09-15] 取标识所属科室名（供通知解析「相关科室管理员」收件人）"""
    try:
        dept = getattr(s, "department", None)
        return getattr(dept, "name", None) if dept is not None else None
    except Exception:
        return None


def _notify_signage_change(
    db: Session, current_user: User, obj_label: str, summary: str,
    signage_id: int | None = None, department: str | None = None,
) -> None:
    """[新增 2026-09-15] 标识变更站内信（统一出口，失败静默，不影响业务主流程）

    标识的增删改、批量操作、附件上传此前只写系统日志，管理方无从知晓；
    这里在每个写端点留痕后补发通知（事件：signage.changed）。
    """
    try:
        modifier_name = getattr(current_user, "name", None) or current_user.employee_id
        notify_super_admins(
            db,
            title=f"标识变更：{obj_label}",
            content=f"{modifier_name} {summary}",
            related_type="signage",
            related_id=signage_id,
            department=department,
            exclude_user_id=current_user.employee_id,
            event_code="signage.changed",
            context={"操作人": modifier_name, "对象": obj_label, "变更内容": summary},
        )
        db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=SignageListResponse)
def list_signages(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    category: str | None = Query(None),
    status: str | None = Query(None),
    campus: str | None = Query(None),
    building: str | None = Query(None),
    # [新增 2026-09-07] 楼层筛选：与列表页筛选栏联动
    floor: str | None = Query(None),
    department_id: int | None = Query(None),
    # [修复 2026-09-05] 标记管理：排除已被标记过的标识（每个标识仅可被标记一次）
    exclude_marked: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取标识列表"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    # [新增 2026-09-08] 按角色科室作用域过滤：非 all 范围的角色仅能获取其所属科室的标识
    allowed = None
    if _get_role_dept_scope(current_user) != "all":
        allowed = get_user_department_scope(current_user, db)
    items, total = get_signage_list(db, page, page_size, search, category, status, campus, building, floor, department_id, exclude_marked, allowed_department_ids=allowed)
    return SignageListResponse(total=total, items=items, page=page, page_size=page_size)


@router.get("/by-code/{code}", response_model=SignageResponse)
def get_signage_by_code_api(
    code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-05] 按标识编码精确查询（移动巡检手输/扫码用）"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    s = get_signage_by_code(db, code)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在")
    return s


@router.post("", response_model=SignageResponse, status_code=201)
def create_signage_endpoint(
    data: SignageCreate,
    request: Request,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_CREATE)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 创建标识"""
    s = create_signage(db, data.model_dump(), current_user.employee_id)
    db.commit()
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_create", current_user.employee_id, detail=f"code={s.code}", target=str(s.id), ip_address=client_ip)
        db.commit()
    except Exception: pass
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_signage_change(
        db, current_user, s.code,
        f"新增了标识「{s.name}」（分类: {s.category}）", s.id, _dept_name_of(s),
    )
    return s


@router.get("/overview")
def signage_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-09] 标识总览聚合数据：KPI / 分类·院区·楼栋分布 / 维修概况 / 最近动态。

    供「标识总览」页一次拉取全部统计，避免前端拼装多个接口；权限与标识列表一致（signage.view）。
    注意：本接口必须声明在 `/{signage_id}` 之前，否则会被通配路由匹配为标识详情。
    """
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    from app.services.signage_overview_service import build_overview
    return build_overview(db)


@router.get("/overview/inspection-trend")
def signage_inspection_trend(
    start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD（默认近 30 天）"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD（默认今天，最多 90 天）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-09] 巡检提交量趋势：按北京日期逐日统计，区间最多 90 天。"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    from datetime import datetime as dt, timedelta
    from app.services.signage_overview_service import inspection_trend
    from app.utils import beijing_today
    today = beijing_today()
    try:
        end = dt.strptime(end_date.strip(), "%Y-%m-%d").date() if end_date else today
        start = dt.strptime(start_date.strip(), "%Y-%m-%d").date() if start_date else (today - timedelta(days=29))
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")
    try:
        items = inspection_trend(db, start, end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"start_date": str(start), "end_date": str(end), "items": items}


@router.get("/{signage_id}", response_model=SignageResponse)
def get_signage_endpoint(
    signage_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取标识详情"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    s = get_signage(db, signage_id)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在")
    # [新增 2026-09-07] 计算最近一次巡检日期并挂载到对象上，供详情页展示
    latest = db.query(SignageInspection).filter(
        SignageInspection.signage_id == s.id
    ).order_by(SignageInspection.inspection_date.desc()).first()
    s.last_inspection_date = latest.inspection_date if latest else None
    return s


def _check_signage_department_access(db: Session, user: User, signage) -> None:
    """[修复/问题5] 校验操作者是否在目标标识所属科室的数据范围内。

    列表接口已用 allowed_department_ids 做过过滤，但更新 / 删除 / 上传接口
    原先只校验权限点（signage.edit / signage.delete），完全不校验科室数据范围，
    导致具备 signage.edit 的 A 科室管理员可越权修改、删除 B 科室的标识，
    或向其上传附件。
    """
    from app.dependencies import has_department_access

    dept = getattr(signage, "department", None)
    dept_name = getattr(dept, "name", None) if dept is not None else None
    if not dept_name:
        # 未归属科室的标识不做范围限制（保持原有行为）
        return
    try:
        if has_department_access(user, dept_name, db):
            return
    except Exception:
        # 校验异常时不阻断业务，交由权限点兜底
        return
    raise HTTPException(status_code=403, detail="无权操作其他科室的标识")


@router.put("/{signage_id}", response_model=SignageResponse)
def update_signage_endpoint(
    signage_id: int,
    data: SignageUpdate,
    oa_number: str = Query("", description="OA单号（选填）"),
    # [新增 2026-09-09] 仅详情页「版本更新」入口传 true：本次修改写入历史版本；普通编辑不记录
    record_history: bool = Query(False, description="是否记录历史版本（版本更新入口为 true）"),
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_EDIT)),
    db: Session = Depends(get_db),
):
    """[修复 2026-09-03] 更新标识（OA单号改为选填）"""
    # [修复 2026-09-03] 移除OA单号必填验证
    # [修复/问题5] 先取出目标标识做科室数据范围校验，通过后再执行更新
    _existing = get_signage(db, signage_id)
    if not _existing:
        raise HTTPException(status_code=404, detail="标识不存在")
    _check_signage_department_access(db, current_user, _existing)
    # [新增 2026-09-15] 变更前快照：同一 session 内的实例更新后读到的是新值，
    # 必须在 update 之前取旧值，否则站内信摘要永远比不出差异
    updates = data.model_dump(exclude_unset=True)
    _old_snapshot = {k: getattr(_existing, k, None) for k in updates.keys()}
    s = update_signage(db, signage_id, updates, current_user.employee_id, oa_number or None, record_history=record_history)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在")
    # [新增 2026-09-05] 临时标识必须填写有效期限
    if s.validity_type == "temporary" and not s.validity_until:
        db.rollback()
        raise HTTPException(status_code=400, detail="临时标识必须填写有效期限")
    db.commit()
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_update", current_user.employee_id, detail=f"oa={oa_number or 'N/A'}", target=str(signage_id), ip_address=client_ip)
        db.commit()
    except Exception: pass
    # [新增 2026-09-15] 补发站内信（事件：signage.changed；仅在字段确有变化时发送）
    try:
        changes = []
        for key, new_val in updates.items():
            old_val = _old_snapshot.get(key)
            if str(old_val or "") == str(new_val or ""):
                continue
            if key == "department_id":
                _ids = [i for i in (old_val, new_val) if i]
                _names = {d.id: d.name for d in db.query(Department).filter(Department.id.in_(_ids)).all()} if _ids else {}
                changes.append(f"关联科室: {_names.get(old_val, '未设置')} → {_names.get(new_val, '未设置')}")
            else:
                changes.append(
                    f"{_SIGNAGE_FIELD_LABELS.get(key, key)}: "
                    f"{_fmt_signage_value(key, old_val)} → {_fmt_signage_value(key, new_val)}"
                )
        if changes:
            changes_str = "；".join(changes[:8]) + ("…" if len(changes) > 8 else "")
            _notify_signage_change(
                db, current_user, s.code,
                "修改了标识「{}」：{}".format(s.name, changes_str),
                s.id, _dept_name_of(s),
            )
    except Exception:
        db.rollback()
    return s


@router.delete("/{signage_id}")
def delete_signage_endpoint(
    signage_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_DELETE)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 删除标识"""
    s = get_signage(db, signage_id)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在")
    # [修复/问题5] 科室数据范围校验
    _check_signage_department_access(db, current_user, s)
    # [新增 2026-09-15] 删除前记录名称与科室，供通知摘要使用
    code, s_name, s_dept = s.code, s.name, _dept_name_of(s)
    delete_signage(db, signage_id)
    db.commit()
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_delete", current_user.employee_id, detail=f"code={code}", target=str(signage_id), ip_address=client_ip)
        db.commit()
    except Exception: pass
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_signage_change(db, current_user, code, f"删除了标识「{s_name}」", signage_id, s_dept)
    return {"message": "删除成功"}


@router.get("/{signage_id}/history", response_model=SignageHistoryListResponse)
def get_history_endpoint(
    signage_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取标识变更历史"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    items, total = get_signage_history(db, signage_id, page, page_size)
    return SignageHistoryListResponse(total=total, items=items, page=page, page_size=page_size)


@router.post("/{signage_id}/photos", response_model=SignagePhotoResponse, status_code=201)
def upload_photo_endpoint(
    signage_id: int,
    data: SignagePhotoCreate,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_EDIT)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 上传标识照片"""
    s = get_signage(db, signage_id)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在")
    # [修复/问题5] 科室数据范围校验
    _check_signage_department_access(db, current_user, s)
    p = create_signage_photo(db, signage_id, data.photo_type, "", data.caption, current_user.employee_id)
    db.commit()
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_signage_change(
        db, current_user, s.code,
        f"为标识「{s.name}」新增了{_photo_type_label(data.photo_type)}照片记录", s.id, _dept_name_of(s),
    )
    return p


@router.get("/{signage_id}/photos")
def list_photos_endpoint(
    signage_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取标识照片列表"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    return get_signage_photos(db, signage_id)


# [修复 2026-09-03] 新增标识设计文件和现场照片上传接口
@router.post("/{signage_id}/upload")
async def upload_signage_photo(
    signage_id: int,
    file: UploadFile = File(...),
    photo_type: str = Query("design", description="照片类型: design(设计文件)/installation(现场照片)"),
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_EDIT)),
    db: Session = Depends(get_db),
):
    """上传标识设计文件或现场照片"""
    # 验证标识是否存在
    s = get_signage(db, signage_id)
    if not s:
        raise HTTPException(status_code=404, detail="标识不存在")
    # [修复/问题5] 科室数据范围校验（防止跨科室上传设计文件/现场照片）
    _check_signage_department_access(db, current_user, s)

    # 验证photo_type参数
    if photo_type not in ("design", "installation"):
        photo_type = "design"

    # 保存文件
    try:
        # [修复 2026-09-03] 使用专用的设计文件上传函数，支持.ai和.pdf格式
        file_path = await save_signage_design_file(file, s.code, photo_type)
    except HTTPException:
        raise
    except Exception as e:
        # [新增 2026-09-09] 文件保存失败记入系统日志（ERROR），避免根因丢失
        logger.error(f"上传标识照片失败: signage_id={signage_id}, code={s.code}, photo_type={photo_type}: {e}", exc_info=True)
        # [修复/问题6] 内部异常详情（磁盘绝对路径、SQLite 错误信息等）不再返回客户端，
        # 仅写入服务端日志，对外统一文案
        import logging
        logging.getLogger(__name__).error(f"文件保存失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="文件保存失败，请联系管理员")

    # 更新标识的对应字段
    if photo_type == "design":
        # 如果有旧照片，删除旧文件
        if s.design_photo:
            delete_file(s.design_photo)
        s.design_photo = file_path
    else:
        # 如果有旧照片，删除旧文件
        if s.installation_photo:
            delete_file(s.installation_photo)
        s.installation_photo = file_path

    db.commit()

    # [新增 2026-09-09] 标识照片上传审计留痕（归集到系统日志）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_photo_upload", current_user.employee_id,
                     detail=f"code={s.code}, type={photo_type}, file={file.filename}",
                     target=str(signage_id), ip_address=client_ip)
        db.commit()
    except Exception: pass

    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_signage_change(
        db, current_user, s.code,
        f"上传了标识「{s.name}」的{_photo_type_label(photo_type)}（文件 {file.filename}）",
        s.id, _dept_name_of(s),
    )

    return {
        "message": "照片上传成功",
        "file_path": file_path,
        "photo_type": photo_type,
    }
