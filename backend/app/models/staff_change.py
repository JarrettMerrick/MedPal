# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""人员信息变更申请模型。

[新增 2026-09-11] 人员信息「立即生效 + 追认审核」的最小实现：

业务背景
--------
个人中心 / 人员编辑 / 照片上传都会直接改动 `staff` 主表（立即生效，保证
「修改后立即显示最新页面」），但敏感字段必须经**科室负责人或超级管理员**
追认审核：

    - 审核通过 → 追认（延迟生效字段在此刻写入主表），变更正式定案；
    - 审核驳回 → 回滚到提交前的旧值（若期间无人再改动该字段），并发站内信告知。

设计要点
--------
- `payload` / `before_snapshot` 均为 JSON：前者是本次提交的新值，后者是提交前
  旧值（回滚源）。二者同时保留，使「立即生效」与「草稿隔离」两种模式可以互换，
  只需调整写入时机。
- 冲突检测**基于字段值比对**（`detect_conflict`），不依赖 `updated_at` 时间戳，
  避免同秒写入或 ORM onupdate 造成的误判。
- 一张表即状态机：pending → approved / rejected / cancelled，
  另附超时提醒（reminded_at）与超时升级（escalated_at）标记。
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base
from app.utils import utc_now

# 审核状态
STATUS_PENDING = "pending"       # 待审核
STATUS_APPROVED = "approved"     # 已通过（追认）
STATUS_REJECTED = "rejected"     # 已驳回（已回滚）
STATUS_CANCELLED = "cancelled"   # 提交人撤回（已回滚）

# 审核层级
LEVEL_NONE = "none"    # 免审（低风险字段，直接生效）
LEVEL_DEPT = "dept"    # 科室负责人审核（无负责人时自动升级超管）
LEVEL_ADMIN = "admin"  # 仅超级管理员审核

# 变更来源
SOURCE_SELF = "self"     # 个人中心自助修改
SOURCE_ADMIN = "admin"   # 人员编辑页（管理端）
SOURCE_PHOTO = "photo"   # 照片上传


class StaffChangeRequest(Base):
    """人员信息变更申请（审核任务 + 回滚快照）"""

    __tablename__ = "staff_change_requests"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="变更申请ID")

    # ---------------- 变更对象 ----------------
    employee_id = Column(String(20), nullable=False, index=True, comment="被修改人员工号")
    # 冗余快照：人员改名/改科室后，审核列表仍能显示提交当时的口径
    staff_name = Column(String(50), nullable=True, comment="提交时的人员姓名")
    department = Column(String(100), nullable=True, index=True,
                        comment="提交时所属科室（用于科室管理员的审核范围过滤）")

    # ---------------- 变更内容 ----------------
    payload = Column(Text, nullable=False, comment="JSON：本次变更的新值")
    before_snapshot = Column(Text, nullable=True, comment="JSON：提交前旧值（驳回/撤回的回滚源）")
    changed_fields = Column(Text, nullable=False, comment="JSON：发生变化的字段名列表")
    change_summary = Column(String(500), nullable=True, comment="人类可读的变更摘要")

    # ---------------- 审核 ----------------
    review_level = Column(String(10), nullable=False, default=LEVEL_DEPT,
                          comment="审核层级：dept 科室负责人 / admin 超级管理员")
    status = Column(String(20), nullable=False, default=STATUS_PENDING, index=True,
                    comment="状态：pending/approved/rejected/cancelled")
    source = Column(String(20), nullable=False, default=SOURCE_ADMIN,
                    comment="变更来源：self 个人中心 / admin 人员编辑 / photo 照片上传")

    submitted_by = Column(String(20), nullable=False, index=True, comment="提交人工号")
    submitted_by_name = Column(String(50), nullable=True, comment="提交人姓名")
    submitted_at = Column(DateTime, default=utc_now, index=True, comment="提交时间（UTC）")

    reviewed_by = Column(String(20), nullable=True, comment="审核人工号")
    reviewed_by_name = Column(String(50), nullable=True, comment="审核人姓名")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间（UTC）")
    reject_reason = Column(String(200), nullable=True, comment="驳回原因")
    review_note = Column(String(100), nullable=True,
                         comment="补充说明：如「超管免审」「无可用审核人，自动通过」")

    # ---------------- 生效 / 回滚 ----------------
    applied_at = Column(DateTime, nullable=True, comment="立即生效时间（UTC）")
    rolled_back = Column(Boolean, nullable=False, default=False, comment="驳回/撤回时是否已回滚")
    rollback_note = Column(String(200), nullable=True, comment="回滚说明（冲突时提示人工核对）")
    conflict_fields = Column(Text, nullable=True, comment="JSON：审核时检测到的冲突字段")

    # ---------------- 超时提醒 / 升级 ----------------
    reminded_at = Column(DateTime, nullable=True, comment="超时提醒时间（UTC，避免重复提醒）")
    escalated_at = Column(DateTime, nullable=True, comment="超时升级到超管的时间（UTC）")

    created_at = Column(DateTime, default=utc_now, index=True, comment="创建时间（UTC）")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(),
                        comment="最后更新时间")
