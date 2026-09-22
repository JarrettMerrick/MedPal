# [调整 2026-09-17] 本模块原为「标识预警」：预警汇总、状态异常、巡检临期/超期、
# 临时标识有效期、维修流程。按需求「标识预警功能删除」后：
#   - 预警类接口（/summary、/abnormal-status、/inspection/*、/validity/expiring、
#     /repairs/in-progress）全部下线，其能力由「标识维修」页（/api/signage-repairs）
#     的「待维修 / 维修处理中」行替代；
#   - 保留维修流程（发起维修 / 上传照片 / 完成维修）与按标识查询维修记录，
#     以及标识标记页所需的异常标识清单（/alerted-signage-ids）。
# 文件保留原路径与路由前缀，避免影响前端既有调用与部署配置。
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import os
import uuid
import logging

logger = logging.getLogger(__name__)

from app.database import get_db
from app.config import settings
# [修复 2026-09-07] 预警接口改用 signage.alert（标识平面 - 查看标识预警）
# [新增 2026-09-09] 维修记录查询接口供详情页使用，与巡检历史一致采用标识查看权限 PERM_SIGNAGE_VIEW
from app.dependencies import (
    get_current_user, has_permission, require_any_permission,
    PERM_SIGNAGE_ALERT, PERM_SIGNAGE_VIEW,
    # [修复 2026-09-17] 维修记录查询补科室数据范围校验
    check_signage_department_access,
)
from app.models.user import User
from app.services.signage_alert_service import (
    # [新增 2026-09-14] 异常标识全量清单（供标识标记页把异常标识高亮显示）
    get_alerted_signage_map,
    # [新增 2026-09-08] 维修流程服务；[新增 2026-09-09] 按标识查询维修记录
    start_repair, complete_repair, get_repairs_by_signage,
)
# [删除 2026-09-17] 不再引入预警专用查询（get_all_alerts / abnormal_status /
# inspections_due_soon / inspections_overdue / expiring_validity / repairs_in_progress）：
# 相关路由已随「标识预警」页下线，计算逻辑仍由「标识总览」在服务层直接调用。
# [新增 2026-09-08] 维修完成照片上传：复用图片校验与落盘逻辑（与巡检照片一致）
# [新增 2026-09-09] 维修流程审计留痕 + 统一 IP 获取
from app.utils import utc_now, get_client_ip
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：报修发起 / 完成通知管理方（此前只留痕不提醒）
from app.services.modification_notify import notify_super_admins
from app.models.signage import Signage
from app.services.upload_service import (
    # [重构 2026-09-21 / Q-7] 照片的校验与保存统一走公共实现
    save_validated_photo,
    validate_image_file, detect_image_format, MAX_FILE_SIZE, UPLOAD_ROOT,
    generate_thumbnail,
)

# [调整 2026-09-17] 路由前缀保持不变（前端维修操作接口依赖，改动会破坏兼容），
# 仅更新分组标签：本模块现只承载「标识维修」流程与异常标识清单
router = APIRouter(prefix="/api/signage-alerts", tags=["标识维修"])

# [新增 2026-09-15] 维修方式中文映射（用于站内信摘要）
_REPAIR_PARTY_LABELS = {"vendor": "供应商维修", "engineering": "工程部维修"}


def _notify_alert_change(db: Session, current_user: User, rec, summary: str) -> None:
    """[新增 2026-09-15] 标识报修站内信（事件：signage.alert_changed，失败静默）"""
    try:
        operator_name = getattr(current_user, "name", None) or current_user.employee_id
        s = db.query(Signage).filter(Signage.id == rec.signage_id).first()
        code = s.code if s else str(rec.signage_id)
        s_name = s.name if s else ""
        dept_name = getattr(getattr(s, "department", None), "name", None) if s else None
        notify_super_admins(
            db,
            title=f"标识报修：{code}",
            content=f"{operator_name} 对标识 {code}「{s_name}」执行了报修操作：{summary}",
            related_type="signage",
            related_id=rec.signage_id,
            department=dept_name,
            exclude_user_id=current_user.employee_id,
            event_code="signage.alert_changed",
            context={"操作人": operator_name, "标识": code, "变更内容": summary},
        )
        db.commit()
    except Exception as e:
        # [修正 2026-09-21 / 代码质量审计 Q-3] 原为「仅 rollback、不留任何日志」，
        # 与 data_io.py 同一形态（2026-09-19 静默异常治理遗漏的写法）。
        # 这里吞掉的是**报修通知的写入失败**：通知发不出去不影响报修本身，
        # 但完全没有痕迹会导致事后无法回答"这条报修到底通知出去了没有"。
        logger.warning(
            "标识报修通知写入失败（已回滚，不影响报修本身）: %s: %s",
            type(e).__name__, e, exc_info=True,
        )
        db.rollback()


def _save_repair_photo(file: UploadFile) -> str:
    """校验并保存维修完成照片，返回相对路径（如 repair/xxx.jpg）。

    [重构 2026-09-21 / 代码质量审计 Q-7] 原实现与巡检照片保存（signage_inspections）
    逐行重复约 30 行，现统一改为调用公共实现 save_validated_photo。
    保留本函数名以不触动既有调用点；文件名规则（repair_时间_随机.ext）与原实现一致。
    """
    return save_validated_photo(file, subdir="repair")
    return f"repair/{filename}"


class RepairStartRequest(BaseModel):
    """[新增 2026-09-08] 发起维修请求"""
    signage_id: int
    # vendor=供应商维修 / engineering=工程部维修
    repair_party: str
    # 供应商维修时的 OA 单号（可选）
    oa_number: Optional[str] = None
    # 供应商维修时必选的供应商 ID
    supplier_id: Optional[int] = None


class RepairCompleteRequest(BaseModel):
    """[新增 2026-09-08] 完成维修请求（维修完成照片可选）"""
    photo: Optional[str] = None


# [删除 2026-09-17] GET /summary（预警汇总）随「标识预警」页一并下线：
# 状态异常标识改由「标识维修」列表（待维修行）统一展示与处理。


@router.get("/alerted-signage-ids")
def alerted_signage_ids(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """[新增 2026-09-14] 处于预警状态的标识清单（标识ID + 预警类型名）。

    供标识标记页把预警标识渲染为醒目样式（红色方框 + 感叹号）。
    与 /summary 判定口径一致，但**不做条数截断**，保证地图上不漏标。
    仅返回标识ID与预警类型中文名，不含任何敏感字段。
    """
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    mapping = get_alerted_signage_map(db)
    return {"items": [{"id": sid, "alerts": labels} for sid, labels in mapping.items()]}


# [删除 2026-09-17] 以下「标识预警」专用接口随预警页一并下线：
#   GET /abnormal-status（状态异常清单）        → 由「标识维修」列表的「待维修」行替代
#   GET /inspection/due-soon、/inspection/overdue（巡检临期 / 超期）
#   GET /validity/expiring（临时标识有效期提醒）
#   GET /repairs/in-progress（维修处理中清单）  → 由「标识维修」列表的「维修处理中」行替代
# 预警计算逻辑（signage_alert_service）仍被「标识总览」复用，故保留在服务层。


# ============================================================
# 维修流程（保留）：标识报修 与 维修记录查询
#   轻微破损/严重损坏 --发起维修--> 维修处理中 --完成维修(可选上传照片)--> 正常
# ============================================================
@router.get("/repairs")
def list_signage_repairs(
    signage_id: int = Query(..., description="标识ID"),
    # [修复 2026-09-17] 权限检查由函数体改为依赖注入：
    # 原先写在函数体内时，缺少 signage_id 参数会先触发 FastAPI 参数校验返回 422
    # （参数校验先于函数体执行），外部观测如同"该路由没有权限校验"；
    # 改为 Depends 后无权限请求直接 403，与同模块其它端点行为一致。
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_VIEW)),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-09] 查询指定标识的全部维修记录（含维修前/后照片路径）。

    供标识详情页「维修记录」弹窗调用。权限与「巡检历史」一致采用标识查看权限，
    保证能查看标识详情的用户均可查看该标识的维修记录。

    [修复 2026-09-17] 补科室数据范围校验：原先仅校验 signage.view 权限点，
    department_scope=own 的受限角色可通过遍历 signage_id 读取其他科室标识的
    维修记录（含维修前后照片路径、供应商名称、OA 单号）。
    """
    s = db.query(Signage).filter(Signage.id == signage_id).first()
    if not s:
        # 保持原行为：标识不存在时返回空列表（前端弹窗展示为空）
        return []
    check_signage_department_access(db, current_user, s)
    return get_repairs_by_signage(db, signage_id)


@router.post("/repairs/start")
def start_signage_repair(body: RepairStartRequest, request: Request = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """发起维修：状态异常（轻微破损/严重损坏）→ 维修处理中。

    - 供应商维修（vendor）：必须选择供应商，OA 单号可选；
    - 工程部维修（engineering）：可直接确认。
    """
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    rec, err = start_repair(db, body.signage_id, body.repair_party, current_user.employee_id, body.oa_number, body.supplier_id)
    if err:
        raise HTTPException(status_code=400, detail=err)
    db.commit()
    # [新增 2026-09-09] 维修发起审计留痕（归集到系统日志）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_repair_start", current_user.employee_id,
                     detail=f"signage_id={rec.signage_id}, party={rec.repair_party}, supplier={rec.supplier_name or '-'}, oa={rec.oa_number or 'N/A'}",
                     target=str(rec.signage_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.alert_changed）
    if rec.repair_party == "vendor":
        _summary = f"发起维修（供应商: {rec.supplier_name or '未指定'}）"
    else:
        _summary = f"发起维修（{_REPAIR_PARTY_LABELS.get(rec.repair_party, rec.repair_party)}）"
    _notify_alert_change(db, current_user, rec, _summary)
    return {
        "id": rec.id, "signage_id": rec.signage_id, "repair_party": rec.repair_party,
        "supplier_name": rec.supplier_name, "oa_number": rec.oa_number,
        "status": "repair_in_progress",
    }


@router.post("/repairs/photo")
async def upload_repair_photo(
    file: UploadFile = File(...),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """[新增 2026-09-08] 上传维修完成照片（客户端已压缩），返回相对路径；完成维修前调用"""
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        file_path = _save_repair_photo(file)
    except Exception as e:
        logger.error(f"上传维修完成照片失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"照片保存失败: {str(e)}")
    db.commit()
    # [新增 2026-09-09] 维修照片上传审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_repair_photo", current_user.employee_id,
                     detail=f"file={file.filename}", target=file_path, ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    return {"file_path": file_path}


@router.post("/repairs/{repair_id}/complete")
def complete_signage_repair(repair_id: int, body: RepairCompleteRequest, request: Request = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """完成维修：维修处理中 → 正常。

    若上传维修完成照片，则同步替换标识详情页的安装现场照片（installation_photo）。
    """
    if not has_permission(current_user, PERM_SIGNAGE_ALERT):
        raise HTTPException(status_code=403, detail="权限不足")
    rec, err = complete_repair(db, repair_id, current_user.employee_id, body.photo)
    if err:
        raise HTTPException(status_code=400, detail=err)
    db.commit()
    # [新增 2026-09-09] 维修完成审计留痕（归集到系统日志）
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_repair_complete", current_user.employee_id,
                     detail=f"repair_id={repair_id}, signage_id={rec.signage_id}, photo={'有' if rec.repair_photo else '无'}",
                     target=str(rec.signage_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.alert_changed）
    _notify_alert_change(
        db, current_user, rec,
        "完成维修，标识状态恢复为正常" + ("（含维修完成照片）" if rec.repair_photo else ""),
    )
    return {
        "id": rec.id, "signage_id": rec.signage_id,
        "repair_photo": rec.repair_photo, "status": "normal",
    }
