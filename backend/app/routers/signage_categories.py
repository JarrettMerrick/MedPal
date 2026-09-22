# [修复 2026-09-04] 标识分类路由
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
# [修复 2026-09-07] 分类写操作改用 signage.category（标识设置 - 标识分类设置）
from app.dependencies import get_current_user, has_permission, require_any_permission, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_CATEGORY
from app.models.user import User
from app.models.signage_settings import SignageCategory
from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
# [新增 2026-09-09] 分类写操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：标识分类增删改后通知管理方（此前只留痕不提醒）
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signage-categories", tags=["标识分类管理"])


# [新增 2026-09-15] 分类字段中文名与取值可读化映射（用于站内信变更摘要）
_CATEGORY_FIELD_LABELS = {
    "name": "名称", "code": "编码", "description": "描述", "color": "颜色",
    "shape": "标记形状", "inspection_cycle_days": "巡检周期(天)", "is_active": "启用状态",
}
_SHAPE_LABELS = {
    "circle": "圆形", "square": "方形", "triangle": "三角形",
    "diamond": "菱形", "star": "星形", "hydrant": "消防栓",
}


def _fmt_category_value(field: str, value) -> str:
    """[新增 2026-09-15] 分类字段值可读化：布尔转启用/停用、形状代码转中文"""
    if value is None or value == "":
        return "空"
    if field == "is_active":
        return "启用" if value else "停用"
    if field == "shape":
        return _SHAPE_LABELS.get(str(value), str(value))
    if field == "inspection_cycle_days":
        return f"{value} 天"
    return str(value)


def _notify_category_change(
    db: Session, current_user: User, cat_label: str, summary: str, cat_id: int | None = None,
) -> None:
    """[新增 2026-09-15] 标识分类变更站内信（统一出口，失败静默）"""
    try:
        modifier_name = getattr(current_user, "name", None) or current_user.employee_id
        notify_super_admins(
            db,
            title=f"标识分类变更：{cat_label}",
            content=f"{modifier_name} {summary}",
            related_type="signage",
            related_id=cat_id,
            exclude_user_id=current_user.employee_id,
            event_code="signage.changed",
            context={"操作人": modifier_name, "对象": cat_label, "变更内容": summary},
        )
        db.commit()
    except Exception:
        db.rollback()


# [修复 2026-09-05] 校验分类颜色：空值允许，非空必须为合法十六进制 #RRGGBB
def _validate_hex_color(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return value
    if not isinstance(value, str) or not value.startswith("#"):
        raise ValueError("颜色必须为十六进制格式（如 #2F9E64）")
    if len(value) != 7:
        raise ValueError("颜色必须为 7 位十六进制（#RRGGBB）")
    try:
        int(value[1:], 16)
    except ValueError:
        raise ValueError("颜色包含非法的十六进制字符")
    return value.upper()


# [修复 2026-09-05] 标记形状取值集合（与前端标记渲染一一对应）
SHAPE_VALUES = {"circle", "square", "triangle", "diamond", "star", "hydrant"}


def _validate_shape(value):
    """[修复 2026-09-05] 校验标记形状：必须是五种预设形状之一"""
    if value in SHAPE_VALUES:
        return value
    raise ValueError("形状必须为 circle/square/triangle/diamond/star/hydrant 之一")


def _validate_cycle(value):
    """[新增 2026-09-05] 校验巡检周期：留空或正整数（天）"""
    if value is None:
        return value
    if value < 1:
        raise ValueError("巡检周期必须为正整数（天）")
    return value


# 数据模型
class SignageCategoryCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    # [修复 2026-09-05] 新增 color 分类颜色
    color: Optional[str] = None
    # [修复 2026-09-05] 新增 shape 标记形状（默认圆形）
    shape: str = "circle"
    # [新增 2026-09-05] 巡检周期（天）：用于巡检到期/超期预警；留空表示该分类不参与巡检预警
    inspection_cycle_days: Optional[int] = None
    is_active: bool = True

    @field_validator("color")
    @classmethod
    def validate_color(cls, v):
        return _validate_hex_color(v)

    @field_validator("shape")
    @classmethod
    def validate_shape(cls, v):
        return _validate_shape(v)

    @field_validator("inspection_cycle_days")
    @classmethod
    def validate_cycle(cls, v):
        return _validate_cycle(v)


class SignageCategoryUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    # [修复 2026-09-05] 新增 color 分类颜色
    color: Optional[str] = None
    # [修复 2026-09-05] 新增 shape 标记形状
    shape: Optional[str] = None
    # [新增 2026-09-05] 巡检周期（天）
    inspection_cycle_days: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("color")
    @classmethod
    def validate_color_update(cls, v):
        return _validate_hex_color(v)

    @field_validator("shape")
    @classmethod
    def validate_shape_update(cls, v):
        if v is None:
            return v
        return _validate_shape(v)

    @field_validator("inspection_cycle_days")
    @classmethod
    def validate_cycle_update(cls, v):
        return _validate_cycle(v)


class SignageCategoryResponse(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str]
    # [修复 2026-09-05] 新增 color 分类颜色
    color: Optional[str] = None
    # [修复 2026-09-05] 新增 shape 标记形状
    shape: str = "circle"
    # [新增 2026-09-05] 巡检周期（天）
    inspection_cycle_days: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SignageCategoryListResponse(BaseModel):
    total: int
    items: List[SignageCategoryResponse]
    page: int
    page_size: int


@router.get("", response_model=SignageCategoryListResponse)
def list_signage_categories(
    page: int = Query(1, ge=1),
    # [修复 2026-09-07] 放宽 page_size 上限至 500，兼容前端一次性拉取全部分类（page_size=200）
    page_size: int = Query(20, ge=1, le=500),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取标识分类列表"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    
    query = db.query(SignageCategory)
    
    if search:
        query = query.filter(
            (SignageCategory.name.contains(search)) |
            (SignageCategory.code.contains(search)) |
            (SignageCategory.description.contains(search))
        )
    
    if is_active is not None:
        query = query.filter(SignageCategory.is_active == is_active)
    
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    
    return SignageCategoryListResponse(
        total=total,
        items=items,
        page=page,
        page_size=page_size
    )


@router.get("/active", response_model=List[SignageCategoryResponse])
def get_active_signage_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取启用的标识分类列表（用于下拉选择）"""
    if not has_permission(current_user, PERM_SIGNAGE_VIEW):
        raise HTTPException(status_code=403, detail="权限不足")
    
    items = db.query(SignageCategory).filter(SignageCategory.is_active == True).all()
    return items


@router.post("", response_model=SignageCategoryResponse, status_code=201)
def create_signage_category(
    data: SignageCategoryCreate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_CATEGORY)),
    db: Session = Depends(get_db),
):
    """创建标识分类"""
    # 检查名称是否已存在
    existing = db.query(SignageCategory).filter(SignageCategory.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="分类名称已存在")
    
    # 检查编码是否已存在
    existing_code = db.query(SignageCategory).filter(SignageCategory.code == data.code).first()
    if existing_code:
        raise HTTPException(status_code=400, detail="分类编码已存在")
    
    item = SignageCategory(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    # [新增 2026-09-09] 标识分类创建审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_category_create", current_user.employee_id,
                     detail=f"name={item.name}, code={item.code}", target=str(item.id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_category_change(
        db, current_user, f"分类「{item.name}」",
        f"新增了标识分类「{item.name}」（代码 {item.code}）", item.id,
    )
    return item


@router.put("/{category_id}", response_model=SignageCategoryResponse)
def update_signage_category(
    category_id: int,
    data: SignageCategoryUpdate,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_CATEGORY)),
    db: Session = Depends(get_db),
):
    """更新标识分类"""
    item = db.query(SignageCategory).filter(SignageCategory.id == category_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="分类不存在")
    
    update_data = data.model_dump(exclude_unset=True)
    
    # 如果更新名称，检查是否与其他分类冲突
    if "name" in update_data and update_data["name"] != item.name:
        existing = db.query(SignageCategory).filter(
            SignageCategory.name == update_data["name"],
            SignageCategory.id != category_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="分类名称已存在")
    
    # 如果更新编码，检查是否与其他分类冲突
    if "code" in update_data and update_data["code"] != item.code:
        existing_code = db.query(SignageCategory).filter(
            SignageCategory.code == update_data["code"],
            SignageCategory.id != category_id
        ).first()
        if existing_code:
            raise HTTPException(status_code=400, detail="分类编码已存在")
    
    # [新增 2026-09-15] 变更前快照：同一 session 实例 setattr 后读到的是新值，
    # 必须在写库之前取旧值，否则站内信摘要永远比不出差异
    _old = {k: getattr(item, k, None) for k in update_data.keys()}
    for key, value in update_data.items():
        setattr(item, key, value)
    
    db.commit()
    db.refresh(item)
    # [新增 2026-09-09] 标识分类更新审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_category_update", current_user.employee_id,
                     detail=f"name={item.name}, code={item.code}", target=str(category_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed；仅在字段确有变化时发送）
    changes = []
    for key, new_val in update_data.items():
        old_val = _old.get(key)
        if str(old_val or "") == str(new_val or ""):
            continue
        changes.append(
            f"{_CATEGORY_FIELD_LABELS.get(key, key)}: "
            f"{_fmt_category_value(key, old_val)} → {_fmt_category_value(key, new_val)}"
        )
    if changes:
        _notify_category_change(
            db, current_user, f"分类「{item.name}」",
            "修改了标识分类「{}」：{}".format(item.name, "；".join(changes[:8])),
            item.id,
        )
    return item


@router.delete("/{category_id}")
def delete_signage_category(
    category_id: int,
    request: Request = None,
    current_user: User = Depends(require_any_permission(PERM_SIGNAGE_CATEGORY)),
    db: Session = Depends(get_db),
):
    """删除标识分类"""
    item = db.query(SignageCategory).filter(SignageCategory.id == category_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="分类不存在")
    
    # [新增 2026-09-09] 删除前记录名称，便于审计详情展示
    cat_name, cat_code = item.name, item.code
    db.delete(item)
    db.commit()
    # [新增 2026-09-09] 标识分类删除审计留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "signage_category_delete", current_user.employee_id,
                     detail=f"name={cat_name}, code={cat_code}", target=str(category_id), ip_address=client_ip)
        db.commit()
    except Exception:
        # [修复 2026-09-19] 原为静默 pass：异常被完全吞掉会让问题无从定位。
        # 此处保持「旁路失败不影响主流程」的语义不变，但降级为 warning 并带堆栈留痕。
        logger.warning(
            "旁路操作失败（已忽略，不影响主流程）", exc_info=True
        )
    # [新增 2026-09-15] 补发站内信（事件：signage.changed）
    _notify_category_change(
        db, current_user, f"分类「{cat_name}」",
        f"删除了标识分类「{cat_name}」（代码 {cat_code}）", category_id,
    )
    return {"message": "删除成功"}