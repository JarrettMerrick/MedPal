# [修复 2026-09-04] 供应商路由
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.database import get_db
# [修复 2026-09-07] 供应商写操作改用 signage.supplier（标识设置 - 供应商设置）
# [修复 2026-09-17] 读接口同步收紧为 signage.supplier（原为 signage.view，导致任意标识查看者
# 可读取供应商联系人个人信息）；下拉接口 /active 按使用场景放行相关权限并裁剪敏感字段
from app.dependencies import (
    has_any_permission, require_any_permission,
    PERM_SIGNAGE_SUPPLIER, PERM_SIGNAGE_CREATE, PERM_SIGNAGE_EDIT,
    PERM_SIGNAGE_ALERT, PERM_SIGNAGE_REPAIR,
)
from app.models.user import User
from app.models.signage_settings import Supplier
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
# [新增 2026-09-09] 供应商写操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：供应商信息变更后通知管理方
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suppliers", tags=["供应商管理"])


def _notify_supplier_change(db: Session, current_user: User, obj_label: str, summary: str) -> None:
    """[新增 2026-09-15] 供应商变更站内信（失败静默）

    供应商信息（名称/类型/联系方式）此前只留痕不提醒，管理方无从知晓；
    在每个写端点留痕后统一补发站内信（事件：supplier.changed）。
    """
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"供应商变更：{obj_label}",
            content=f"{modifier_name} {summary}",
            related_type="supplier",
            exclude_user_id=current_user.employee_id,
            event_code="supplier.changed",
            context={"操作人": modifier_name, "对象": obj_label, "变更内容": summary},
        )
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )


# 数据模型
class SupplierCreate(BaseModel):
    name: str
    type: str = "manufacturer"
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierResponse(BaseModel):
    id: int
    name: str
    type: str
    contact_person: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    email: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SupplierListResponse(BaseModel):
    total: int
    items: List[SupplierResponse]
    page: int
    page_size: int


@router.get("", response_model=SupplierListResponse)
def list_suppliers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_SUPPLIER)),
    db: Session = Depends(get_db),
):
    """获取供应商列表（供应商设置页）。

    [修复 2026-09-17] 读权限由 signage.view 收紧为 signage.supplier：
    本接口返回供应商联系人姓名 / 手机号 / 地址 / 邮箱等第三方个人信息，
    原先任意持有「标识查看」权限的账号（如仅有标识巡检 / 标识查看的科室账号）
    即可批量获取，属功能级授权缺失。现与前端「供应商设置」页的 RoleGuard
    （signage.supplier）及本模块写接口的口径保持一致。
    仅需"选择供应商"下拉的场景请使用 /suppliers/active（按权限返回最小字段集）。
    """
    query = db.query(Supplier)
    
    if search:
        query = query.filter(
            (Supplier.name.contains(search)) |
            (Supplier.contact_person.contains(search)) |
            (Supplier.phone.contains(search))
        )
    
    if is_active is not None:
        query = query.filter(Supplier.is_active == is_active)
    
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    
    return SupplierListResponse(
        total=total,
        items=items,
        page=page,
        page_size=page_size
    )


@router.get("/active")
def get_active_suppliers(
    type: Optional[str] = Query(None, description="供应商类型: manufacturer"),
    current_user: User = Depends(require_any_permission(
        PERM_SIGNAGE_SUPPLIER, PERM_SIGNAGE_CREATE, PERM_SIGNAGE_EDIT,
        PERM_SIGNAGE_ALERT, PERM_SIGNAGE_REPAIR,
    )),
    db: Session = Depends(get_db),
):
    """获取启用的供应商列表（用于下拉选择）。

    [修复 2026-09-17] 权限口径调整与字段裁剪：
    - 本接口被多个功能共用：标识表单供应商下拉（signage.create / signage.edit）、
      标识预警「发起维修」弹窗（signage.alert）、维修记录筛选（signage.repair）。
      原实现要求 signage.view，既过宽（任意标识查看者可读全部个人信息字段），
      又与上述场景权限不匹配。现按场景放行任一相关权限；
    - 返回字段按权限裁剪：联系人 / 电话 / 地址 / 邮箱仅对「供应商设置 / 标识编辑」
      权限返回（标识表单选择供应商后需自动填充联系电话）；预警与维修的下拉场景
      仅需 id/name 展示，只返回 id/name/type，不再下发第三方个人信息。
    """
    query = db.query(Supplier).filter(Supplier.is_active == True)
    
    if type:
        query = query.filter(Supplier.type == type)
    
    items = query.all()
    if not has_any_permission(current_user, PERM_SIGNAGE_SUPPLIER, PERM_SIGNAGE_CREATE, PERM_SIGNAGE_EDIT):
        return [
            {"id": s.id, "name": s.name, "type": s.type, "is_active": s.is_active}
            for s in items
        ]
    return items


@router.post("", response_model=SupplierResponse, status_code=201)
def create_supplier(
    data: SupplierCreate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_SUPPLIER)),
    db: Session = Depends(get_db),
):
    """创建供应商"""
    # 检查名称是否已存在
    existing = db.query(Supplier).filter(Supplier.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="供应商名称已存在")
    
    item = Supplier(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    # [新增 2026-09-09] 供应商创建审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "supplier_create", current_user.employee_id,
                     detail=f"name={item.name}, type={item.type}", target=str(item.id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：supplier.changed）
    _notify_supplier_change(
        db, current_user, item.name,
        f"新增了供应商「{item.name}」（类型 {item.type}）",
    )
    return item


@router.put("/{supplier_id}", response_model=SupplierResponse)
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_SUPPLIER)),
    db: Session = Depends(get_db),
):
    """更新供应商"""
    item = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="供应商不存在")
    
    update_data = data.model_dump(exclude_unset=True)
    
    # 如果更新名称，检查是否与其他供应商冲突
    if "name" in update_data and update_data["name"] != item.name:
        existing = db.query(Supplier).filter(
            Supplier.name == update_data["name"],
            Supplier.id != supplier_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="供应商名称已存在")
    
    for key, value in update_data.items():
        setattr(item, key, value)
    
    db.commit()
    db.refresh(item)
    # [新增 2026-09-09] 供应商更新审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "supplier_update", current_user.employee_id,
                     detail=f"name={item.name}", target=str(supplier_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：supplier.changed；无实际字段变化时不发）
    if update_data:
        _notify_supplier_change(
            db, current_user, item.name,
            "修改了供应商「{}」（字段：{}）".format(item.name, "、".join(update_data.keys())),
        )
    return item


@router.delete("/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_SUPPLIER)),
    db: Session = Depends(get_db),
):
    """删除供应商"""
    item = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="供应商不存在")
    
    # [新增 2026-09-09] 删除前记录名称用于审计详情
    name = item.name
    db.delete(item)
    db.commit()
    # [新增 2026-09-09] 供应商删除审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "supplier_delete", current_user.employee_id,
                     detail=f"name={name}", target=str(supplier_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：supplier.changed）
    _notify_supplier_change(db, current_user, name, f"删除了供应商「{name}」")
    return {"message": "删除成功"}