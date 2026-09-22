# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""[新增 2026-09-15] 通知设置（可配置通知中心）请求模型"""

from typing import Optional

from pydantic import BaseModel, Field


class RecipientRuleItem(BaseModel):
    """单条收件人规则

    type  取值见 notification_center.RECIPIENT_RULE_TYPES
          （super_admins / dept_managers / permissions / roles / departments / users / actor）
    value 需要取值的规则必填（工号、角色名、权限名、科室名列表）
    scope 仅 dept_managers / permissions 支持 "event_department"（限本事件相关科室）
    """
    type: str
    value: Optional[list[str]] = None
    scope: Optional[str] = None


class RecipientRules(BaseModel):
    """自定义收件人规则集合"""
    include: list[RecipientRuleItem] = Field(default_factory=list)
    exclude_actor: bool = True


class NotificationRuleUpdate(BaseModel):
    """保存某事件的规则覆盖

    title_template / content_template 传空字符串表示恢复默认模板；
    recipient_mode='custom' 时必须提供 recipient_rules。
    """
    enabled: bool = True
    title_template: Optional[str] = None
    content_template: Optional[str] = None
    recipient_mode: str = "default"
    recipient_rules: Optional[RecipientRules] = None


class NotificationPreviewRequest(BaseModel):
    """预览（干跑）请求：不传模板/规则时按当前生效配置渲染

    传入即为「未保存草稿」，用于保存前确认效果。
    """
    title_template: Optional[str] = None
    content_template: Optional[str] = None
    recipient_mode: Optional[str] = None
    recipient_rules: Optional[RecipientRules] = None
    department: Optional[str] = None
