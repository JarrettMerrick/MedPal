# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime

from app.database import Base


class PasswordResetTask(Base):
    """[新增 2026-09-15] 批量重置密码任务（后台执行 + 前端进度条）。

    背景：批量重置需为每个账号计算 bcrypt 哈希（约 0.2~0.3s/个），数百个账号
    耗时数十秒~数分钟。同步接口会让前端请求超时，用户在等待中重复点击，进而
    产生多个大事务并发写库（SQLite 写锁冲突 → 数据库错误）。改造为：

      - POST 只做校验并创建任务，立即返回（毫秒级），前端展示进度条；
      - 后台任务分批处理并更新 `processed`，前端按**实际进度**轮询展示；
      - 同一时间只允许一个 running 任务：重复提交会被 409 拦下（前端切换到
        进行中任务的进度展示），从根上避免重复操作。
    """

    __tablename__ = "password_reset_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # running / completed / failed
    status = Column(String(20), nullable=False, default="running")
    total = Column(Integer, nullable=False, default=0)        # 目标账号总数
    processed = Column(Integer, nullable=False, default=0)    # 已处理数（进度）
    inactive_count = Column(Integer, default=0)               # 其中已停用账号数
    super_admin_excluded = Column(Integer, default=0)         # 跳过的超级管理员数
    unassigned_excluded = Column(Integer, default=0)          # 未分配科室被跳过数
    departments = Column(String(500))                         # "||" 分隔；空 = 不限科室（全员）
    is_all_departments = Column(Boolean, default=True)
    password_rule = Column(String(100))                       # 本次生效的口令模板
    is_uniform = Column(Boolean, default=True)                # 模板不含 {工号} → 全员同一口令
    uniform_password = Column(String(100))                    # 统一口令回显（逐人口令时为 NULL）
    self_included = Column(Boolean, default=False)            # 操作者本人在范围内（其 token 已失效）
    message = Column(Text)                                    # 完成后的结果文案
    error = Column(Text)                                      # 失败原因摘要
    created_by = Column(String(20))
    created_by_name = Column(String(50))
    created_at = Column(DateTime)
    finished_at = Column(DateTime)
