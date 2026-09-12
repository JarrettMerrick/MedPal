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
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signage-categories", tags=["标识分类管理"])


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
    except Exception: pass
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
    except Exception: pass
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
    except Exception: pass
    return {"message": "删除成功"}