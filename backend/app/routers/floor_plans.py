import logging
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
from sqlalchemy.orm import Session
from app.database import get_db
# [修复 2026-09-07] 平面图底图管理用 signage.floorplan（标识设置 - 平面设置）；
# 标识点位增删用 signage.marker（标识平面 - 标识标记）
from app.dependencies import get_current_user, has_permission, require_any_permission, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_FLOORPLAN, PERM_SIGNAGE_MARKER
from app.models.user import User
from app.schemas.signage import FloorPlanCreate, FloorPlanResponse, FloorPlanListResponse, SignagePointCreate, SignagePointResponse, SignagePointListResponse
from app.services.signage_service import create_floor_plan, get_floor_plan, get_floor_plan_list, create_signage_point, get_signage_points, delete_signage_point, get_point_by_signage, get_signage
from app.services.upload_service import delete_file
from app.services.upload_service import save_upload_file, UPLOAD_ROOT
# [新增 2026-09-09] 平面图/点位写操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：平面图 / 标识点位变更后通知管理方
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip
import os

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/floor-plans", tags=["平面图管理"])


def _notify_floorplan_change(db: Session, current_user: User, obj_label: str, summary: str) -> None:
    """[新增 2026-09-15] 标识平面变更站内信（平面图 / 点位共用出口，失败静默）

    平面图与标识点位是「标识管理」的展示层数据，改动会直接影响终端导览与
    大屏展示，因此在各写端点留痕后统一补发站内信（事件：signage.changed）。
    """
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"标识平面变更：{obj_label}",
            content=f"{modifier_name} {summary}",
            related_type="signage",
            exclude_user_id=current_user.employee_id,
            event_code="signage.changed",
            context={
                "操作人": modifier_name,
                "对象": obj_label,
                "变更内容": summary,
            },
        )
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )


@router.get("")
def list_floor_plans(
    campus: str | None = Query(None),
    building: str | None = Query(None),
    # [修复 2026-09-05] 新增平面类别过滤（院区平面/楼层平面）
    category: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取平面图列表"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    return get_floor_plan_list(db, campus, building, category)


@router.post("", response_model=FloorPlanResponse, status_code=201)
def create_floor_plan_endpoint(
    data: FloorPlanCreate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_FLOORPLAN)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 创建平面图"""
    p = create_floor_plan(db, data.model_dump())
    db.commit()
    # [新增 2026-09-09] 平面图创建审计留痕
    try:
        record_audit(db, "floorplan_create", current_user.employee_id,
                     detail=f"campus={p.campus}, building={p.building}, floor={p.floor}", target=str(p.id),
                     ip_address=get_client_ip(request))
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_floorplan_change(
        db, current_user, f"平面图 #{p.id}",
        f"创建了平面图（院区={p.campus or '未填'}，楼栋={p.building or '未填'}，楼层={p.floor or '未填'}）",
    )
    return p


@router.get("/{plan_id}", response_model=FloorPlanResponse)
def get_floor_plan_endpoint(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取平面图详情"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    p = get_floor_plan(db, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="平面图不存在")
    return p


@router.delete("/{plan_id}")
def delete_floor_plan_endpoint(
    plan_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_FLOORPLAN)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 删除平面图"""
    p = get_floor_plan(db, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="平面图不存在")
    # [新增 2026-09-15] 删除前保存位置摘要：删除 commit 后 ORM 属性失效，
    # 站内信需要注明「删掉的是哪个位置」的平面图
    _p_loc = f"{p.campus or ''}{p.building or ''}{p.floor or ''}" or f"ID {plan_id}"
    # [修复 2026-09-07] 删除平面图时同步清理图片物理文件（含 thumb_/orig_ 副本），避免孤儿文件
    if p.image_url:
        delete_file(p.image_url)
    db.delete(p)
    db.commit()
    # [新增 2026-09-09] 平面图删除审计留痕
    try:
        record_audit(db, "floorplan_delete", current_user.employee_id,
                     detail=f"plan_id={plan_id}", target=str(plan_id),
                     ip_address=get_client_ip(request))
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_floorplan_change(db, current_user, f"平面图 #{plan_id}", f"删除了平面图「{_p_loc}」")
    return {"message": "删除成功"}


@router.post("/{plan_id}/points", response_model=SignagePointResponse, status_code=201)
def create_point_endpoint(
    plan_id: int,
    data: SignagePointCreate,
    # [修复 2026-09-05] 重新绑定时豁免旧点位的重复校验（前端先建新、后删旧，避免失败丢标记）
    exclude_point_id: int | None = Query(None),
    # [修复 2026-09-07] 点位创建属「标识标记」权限（signage.marker）
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_MARKER)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 创建标识点位"""
    p = get_floor_plan(db, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="平面图不存在")
    # [修复 2026-09-05] 每个标识全局仅可被标记一次
    if get_point_by_signage(db, data.signage_id, exclude_point_id):
        raise HTTPException(status_code=400, detail="该标识已被标记，不能重复标记")
    data.floor_plan_id = plan_id
    point = create_signage_point(db, data.model_dump())
    db.commit()
    # [新增 2026-09-09] 标识点位创建审计留痕
    try:
        record_audit(db, "marker_create", current_user.employee_id,
                     detail=f"plan_id={plan_id}, signage_id={data.signage_id}", target=str(point.id),
                     ip_address=get_client_ip(request))
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_floorplan_change(
        db, current_user, f"标识点位 #{point.id}",
        f"在平面图 #{plan_id} 上新增了标识点位（标识 ID {data.signage_id}）",
    )
    # [修复 2026-09-05] 响应附带标识信息，保证新标记点立即按分类样式渲染
    sg = get_signage(db, data.signage_id)
    return SignagePointResponse(
        id=point.id,
        signage_id=point.signage_id,
        floor_plan_id=point.floor_plan_id,
        x_percent=point.x_percent,
        y_percent=point.y_percent,
        pin_icon=point.pin_icon,
        pin_color=point.pin_color,
        signage_category=sg.category if sg else None,
        signage_code=sg.code if sg else None,
        signage_name=sg.name if sg else None,
    )


@router.get("/{plan_id}/points")
def list_points_endpoint(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 获取平面图的所有标识点位"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    p = get_floor_plan(db, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="平面图不存在")
    pts = get_signage_points(db, plan_id)
    # [修复 2026-09-05] 附带标识编码/名称/分类：标记点按「分类形状+颜色」渲染，
    # 不能依赖前端绑定弹窗的分页标识列表（已被 exclude_marked 过滤，查不到已标记的标识）
    out = []
    for pt in pts:
        sg = get_signage(db, pt.signage_id)
        out.append({
            "id": pt.id,
            "signage_id": pt.signage_id,
            "floor_plan_id": pt.floor_plan_id,
            "x_percent": pt.x_percent,
            "y_percent": pt.y_percent,
            "pin_icon": pt.pin_icon,
            "pin_color": pt.pin_color,
            "signage_category": sg.category if sg else None,
            "signage_code": sg.code if sg else None,
            "signage_name": sg.name if sg else None,
        })
    return out


@router.delete("/points/{point_id}")
def delete_point_endpoint(
    point_id: int,
    # [修复 2026-09-07] 点位删除属「标识标记」权限（signage.marker）
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_MARKER)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-03] 删除标识点位"""
    success = delete_signage_point(db, point_id)
    if not success:
        raise HTTPException(status_code=404, detail="点位不存在")
    db.commit()
    # [新增 2026-09-09] 点位删除审计留痕
    try:
        record_audit(db, "marker_delete", current_user.employee_id,
                     detail=f"point_id={point_id}", target=str(point_id),
                     ip_address=get_client_ip(request))
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_floorplan_change(db, current_user, f"标识点位 #{point_id}", "删除了平面图上的标识点位")
    return {"message": "删除成功"}


@router.post("/{plan_id}/upload", response_model=FloorPlanResponse)
async def upload_floor_plan_image(
    plan_id: int,
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_FLOORPLAN)),
    db: Session = Depends(get_db),
):
    """[修复 2026-09-03] 上传平面图图片"""
    # 检查平面图是否存在
    p = get_floor_plan(db, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="平面图不存在")
    
    # 保存上传的图片
    try:
        # 使用现有的上传服务保存图片
        # entity_type使用"floor_plan"，entity_id使用平面图ID
        image_url = await save_upload_file(
            file=file,
            entity_type="floor_plan",
            entity_id=str(plan_id),
            photo_type="image",
            min_width=400,
            min_height=300,
            # [修复 2026-09-05] 平面图支持上传 SVG 矢量图
            allow_svg=True
        )

        # [修复 2026-09-07] 重复上传时清理旧图片物理文件（每次上传生成新文件名，旧图不再被引用）
        if p.image_url:
            delete_file(p.image_url)

        # 更新平面图的image_url字段
        p.image_url = image_url
        db.commit()
        db.refresh(p)
        
        # [新增 2026-09-09] 平面图图片上传审计留痕
        try:
            record_audit(db, "floorplan_upload", current_user.employee_id,
                         detail=f"plan_id={plan_id}, file={file.filename}", target=str(plan_id),
                         ip_address=get_client_ip(request))
            db.commit()
        except Exception:
            # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
            # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
            logger.warning(
                "旁路操作失败（已忽略，不影响主流程）", exc_info=True
            )
        # [新增 2026-09-15] 补发站内信（事件：signage.changed）
        _notify_floorplan_change(
            db, current_user, f"平面图 #{plan_id}",
            f"上传/更换了平面图底图（{file.filename}）",
        )

        return p
    except Exception as e:
        # [新增 2026-09-09] 平面图图片上传失败记入运行日志（ERROR），根因可查
        logger.error(f"上传平面图图片失败: plan_id={plan_id}, {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.put("/{plan_id}/image", response_model=FloorPlanResponse)
async def update_floor_plan_image(
    plan_id: int,
    data: FloorPlanCreate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_FLOORPLAN)),
    db: Session = Depends(get_db),
):
    """[修复 2026-09-03] 更新平面图信息（包括image_url）"""
    p = get_floor_plan(db, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="平面图不存在")

    # [修复 2026-09-07] 记录旧图路径：若本次更新替换了 image_url，清理旧图片物理文件，避免孤儿残留
    old_image_url = p.image_url

    # 更新平面图信息
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(p, key, value)

    if old_image_url and p.image_url != old_image_url:
        delete_file(old_image_url)
    
    db.commit()
    db.refresh(p)
    # [新增 2026-09-09] 平面图更新审计留痕
    try:
        record_audit(db, "floorplan_update", current_user.employee_id,
                     detail=f"plan_id={plan_id}, image_changed={bool(old_image_url and p.image_url != old_image_url)}",
                     target=str(plan_id), ip_address=get_client_ip(request))
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_floorplan_change(
        db, current_user, f"平面图 #{plan_id}",
        "更新了平面图信息" + ("（底图已更换）" if old_image_url and p.image_url != old_image_url else ""),
    )
    return p
