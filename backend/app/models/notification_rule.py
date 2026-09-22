# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""通知规则模型（系统设置 → 通知设置）

[新增 2026-09-15] 「可配置通知中心」
=====================================
背景：站内信的系统通知（人员变更 / 工卡 / 系统告警等）此前把「标题、正文、收件人」
全部硬编码在各业务调用点（notify_super_admins / create_notification），各单位无法按
自身管理习惯调整——例如希望「人员信息被修改」只通知本科室管理员而不通知超管，
或希望在正文前加上本单位统一的提示语。

设计：**事件注册表（代码） + 规则覆盖（数据库）** 两层。
    - 事件清单、默认开关、默认文案模板、可用变量、默认收件人范围，全部由
      `app/services/notification_center.py` 的注册表定义，随版本演进；
    - 本表只存「管理员改过的部分」（覆盖）。**未改过的事件不落库**：
      这样升级后新增的事件会自动出现在设置页，且未配置时的通知行为与改造前
      逐字一致（默认模板即原硬编码文案）。
    - 「恢复默认」= 删除本行，回到注册表默认，而不是写回一份默认值副本，
      避免历史默认值固化后与代码演进脱节。

字段取值约定：
    - enabled=False：该事件不再发送站内信（业务数据不变，仅不产生通知）；
    - title_template / content_template 为 NULL：沿用注册表默认模板；
    - recipient_mode='default'：沿用该事件的业务内置收件人范围（改造前行为）；
      'custom'：按 recipient_rules（JSON）解析收件人。
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.database import Base
from app.utils import utc_now

# 收件人模式
RECIPIENT_MODE_DEFAULT = "default"  # 业务内置默认范围
RECIPIENT_MODE_CUSTOM = "custom"    # 管理员自定义规则


class NotificationRule(Base):
    """单个通知事件的规则覆盖（一行 = 一个事件）"""

    __tablename__ = "notification_rules"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    event_code = Column(
        String(64), nullable=False, unique=True, index=True,
        comment="事件编码（与 notification_center.NOTIFICATION_EVENTS 对应）",
    )
    enabled = Column(Boolean, nullable=False, default=True, comment="是否发送该事件的通知")
    title_template = Column(
        String(200), nullable=True, comment="标题模板（支持 {变量}）；NULL 表示用默认",
    )
    content_template = Column(
        Text, nullable=True, comment="正文模板（支持 {变量}，允许简单 HTML）；NULL 表示用默认",
    )
    recipient_mode = Column(
        String(16), nullable=False, default=RECIPIENT_MODE_DEFAULT,
        comment="收件人模式：default 业务内置 / custom 自定义规则",
    )
    recipient_rules = Column(
        Text, nullable=True, comment="自定义收件人规则（JSON 文本，仅 custom 模式使用）",
    )
    updated_by = Column(String(20), nullable=True, comment="最后修改人工号")
    updated_at = Column(DateTime, nullable=True, default=utc_now, onupdate=utc_now,
                        comment="最后修改时间（UTC）")
