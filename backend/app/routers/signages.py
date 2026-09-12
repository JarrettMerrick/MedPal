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
from app.services.upload_service import save_upload_file, save_signage_design_file, delete_file
# [新增 2026-09-09] 统一 IP 获取（兼容反向代理）
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signages", tags=["标识管理"])


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
    s = update_signage(db, signage_id, data.model_dump(exclude_unset=True), current_user.employee_id, oa_number or None, record_history=record_history)
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
    code = s.code
    delete_signage(db, signage_id)
    db.commit()
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_delete", current_user.employee_id, detail=f"code={code}", target=str(signage_id), ip_address=client_ip)
        db.commit()
    except Exception: pass
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

    return {
        "message": "照片上传成功",
        "file_path": file_path,
        "photo_type": photo_type,
    }
