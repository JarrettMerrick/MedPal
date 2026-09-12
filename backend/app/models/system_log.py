# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

# [修复 2026-09-01] 新增系统日志模型，支持操作日志、系统日志、错误日志的统一存储与查询

from sqlalchemy import Column, DateTime, Integer, String, Text, Index
from sqlalchemy.sql import func

from app.database import Base


class SystemLog(Base):
    """系统日志表 —— 记录操作日志、系统日志、错误日志"""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="日志ID")
    timestamp = Column(DateTime, nullable=False, server_default=func.now(), comment="日志时间")
    level = Column(String(10), nullable=False, default="INFO", comment="日志级别: INFO/WARN/ERROR")
    category = Column(String(20), nullable=False, default="operation", comment="日志类别: operation-操作日志/system-系统日志/error-错误日志")
    operator = Column(String(20), nullable=True, comment="操作人工号（系统日志可为空）")
    content = Column(Text, nullable=False, comment="日志内容")
    ip_address = Column(String(45), nullable=True, comment="客户端IP地址")
    details = Column(Text, nullable=True, comment="详细信息（JSON 或补充说明）")

    # 复合索引：加速按时间+类别+级别的常见查询
    __table_args__ = (
        Index("ix_system_logs_ts_cat", "timestamp", "category"),
        Index("ix_system_logs_ts_level", "timestamp", "level"),
    )
