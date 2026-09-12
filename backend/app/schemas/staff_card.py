# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StaffCardCreate(BaseModel):
    """创建卡片请求"""
    entity_type: str = Field(..., description="实体类型: doctor/nurse")
    entity_id: str = Field(..., description="实体工号")
    card_photo: str = Field(..., description="卡片照片路径")


class StaffCardUpdate(BaseModel):
    """更新卡片状态"""
    status: str = Field(..., description="卡片状态: confirmed/rejected")
    reject_reason: str | None = Field(None, description="拒绝原因")


class StaffCardResponse(BaseModel):
    """卡片响应"""
    id: int
    entity_type: str
    entity_id: str
    card_photo: str
    status: str
    uploaded_by: str
    uploaded_at: datetime
    confirmed_by: Optional[str] = None
    confirmed_by_name: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    # [改进] 当前登录用户是否可确认/拒绝该卡片：
    # - 员工本人可确认自己的卡片（无需 card.upload 权限）
    # - 持有 card.upload 权限者可在管辖范围内确认他人卡片
    # 由后端在列表/详情接口计算返回，前端据此渲染操作按钮，保证前后端权限一致
    can_confirm: bool = False

    class Config:
        from_attributes = True


class StaffCardListResponse(BaseModel):
    """卡片列表响应"""
    total: int
    items: list[StaffCardResponse]
    page: int
    page_size: int
