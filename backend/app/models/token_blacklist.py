# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base
from app.utils import utc_now


class TokenBlacklist(Base):
    """Token 黑名单，用于使已签发的 token 失效"""
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(500), nullable=False, unique=True, index=True, comment="被废弃的 token")
    token_type = Column(String(20), nullable=False, comment="token 类型: access/refresh")
    employee_id = Column(String(20), nullable=True, comment="关联的工号")
    reason = Column(String(100), nullable=True, comment="废弃原因: logout/password_reset/account_disabled")
    created_at = Column(DateTime, default=utc_now, comment="加入黑名单时间（UTC）")
    expires_at = Column(DateTime, nullable=False, comment="token 原始过期时间")