# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SystemConfigOut(BaseModel):
    """系统配置输出"""
    id: int
    config_key: str
    config_value: Optional[str] = None
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SystemConfigUpdate(BaseModel):
    """系统配置更新"""
    config_value: str
    description: str | None = None