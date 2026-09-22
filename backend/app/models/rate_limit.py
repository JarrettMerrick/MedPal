# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.database import Base
from app.utils import utc_now


class RateLimitRecord(Base):
    """登录 / 刷新等敏感接口的限流计数（对应审计问题 14）

    旧实现把失败计数保存在进程内存字典 `_IP_FAIL` 中，存在两个问题：
      1. 多 worker / 多实例部署时每个进程各持一份计数，
         攻击者把请求分散到不同进程即可轻松绕过限流；
      2. 进程重启计数即清零。

    改为持久化到数据库后，所有进程共享同一份计数，重启亦不失效。
    """
    __tablename__ = "rate_limit_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(64), nullable=False, index=True, comment="来源 IP")
    action = Column(String(32), nullable=False, index=True, comment="限流动作: login/refresh")
    attempts = Column(Integer, nullable=False, default=0, comment="当前窗口内的尝试次数")
    window_start = Column(DateTime, nullable=False, default=utc_now, comment="当前统计窗口起点（UTC）")
    blocked_until = Column(DateTime, nullable=True, comment="封禁截止时刻（UTC），为空表示未封禁")

    __table_args__ = (
        UniqueConstraint("ip_address", "action", name="uq_rate_limit_ip_action"),
    )
