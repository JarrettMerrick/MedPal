# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""站内信接口的请求模型"""

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class SendMessageRequest(BaseModel):
    """发送站内信（私发 / 群发）"""

    title: str = Field(..., min_length=1, max_length=200, description="标题")
    content: str = Field(default="", description="正文（富文本 HTML）")
    send_type: str = Field(default="direct", description="direct 私发 / broadcast 群发")
    # 私发：指定工号列表
    recipients: list[str] = Field(default_factory=list, description="私发收件人工号列表")
    # 群发：目标类型 + 取值
    target_type: Optional[str] = Field(
        None, description="all 全员 / departments 按科室 / roles 按角色 / permissions 按权限 / users 指定工号",
    )
    target_values: list[str] = Field(default_factory=list, description="群发目标取值")

    @model_validator(mode="after")
    def check_target(self):
        if self.send_type not in ("direct", "broadcast"):
            raise ValueError("send_type 仅支持 direct / broadcast")
        if self.send_type == "direct":
            if not [r for r in self.recipients if (r or "").strip()]:
                raise ValueError("私发至少需要选择一名收件人")
        else:
            if not self.target_type:
                raise ValueError("群发需要指定 target_type")
            if self.target_type not in ("all", "departments", "roles", "permissions", "users"):
                raise ValueError("target_type 取值无效")
            if self.target_type != "all" and not [v for v in self.target_values if (v or "").strip()]:
                raise ValueError("群发需要指定目标范围")
        return self


class RecipientPreviewRequest(BaseModel):
    """群发前预览收件人"""

    target_type: str
    target_values: list[str] = Field(default_factory=list)


class MessageIdsRequest(BaseModel):
    """按消息ID批量操作"""

    ids: list[int] = Field(default_factory=list)


class MarkReadRequest(MessageIdsRequest):
    is_read: bool = True


class MessageFlagsRequest(MessageIdsRequest):
    """标注：星标 / 归档 / 自定义标签（字段不传=不修改）"""

    is_starred: Optional[bool] = None
    is_archived: Optional[bool] = None
    tag_id: Optional[int] = None
    clear_tag: bool = Field(default=False, description="为 true 时清除标签（优先级高于 tag_id）")


class MessageTagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    color: Optional[str] = Field(default=None, max_length=20)


class MessageTagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=30)
    color: Optional[str] = Field(default=None, max_length=20)
