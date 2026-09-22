# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""人员信息变更审核相关的请求/响应模型。

[新增 2026-09-11] 列表接口直接返回 dict（字段由 staff_change_service.serialize
统一裁剪，避免把 payload 全量下发），此文件只定义请求体。
"""

from pydantic import BaseModel, Field


class StaffChangeReject(BaseModel):
    """驳回人员信息变更（必须填写原因）"""
    reason: str = Field(..., min_length=1, max_length=200, description="驳回原因")
