# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.staff import Staff
from app.models.user_department_scope import UserDepartmentScope
from app.schemas.staff import StaffCreate, StaffUpdate
# [统一时间口径] 输出给前端的时间字段统一 to_iso_utc（带 Z 的 UTC）
from app.utils import utc_now, to_iso_utc

# [新增 2026-09-11] 离职保留期（天）：离职满该期限后「仅保留统计」，
# 由定时任务私信超管提醒手动删除其登录账号（见 backup_service.notify_resigned_accounts）
RESIGN_RETENTION_DAYS = 180  # 6 个月


# ==================== 查询 ====================

def get_staff_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    department: str | None = None,
    work_type: str | None = None,
    department_filter: str | None = None,
    work_type_filter: str | None = None,
    status: str | None = "active",
) -> tuple[list[Staff], int]:
    """获取人员列表（分页+搜索+筛选）"""
    query = db.query(Staff)

    # 状态筛选
    if status:
        query = query.filter(Staff.status == status)

    # 工种筛选（用户主动选择）
    if work_type:
        query = query.filter(Staff.work_type == work_type)

    # 工种范围过滤（基于权限的强制限制，逗号分隔）
    if work_type_filter and not work_type:
        wt_list = [w.strip() for w in work_type_filter.split(",") if w.strip()]
        if wt_list:
            query = query.filter(Staff.work_type.in_(wt_list))

    # 按部门过滤（支持逗号分隔的多个部门名称）
    if department_filter:
        dept_list = [d.strip() for d in department_filter.split("||") if d.strip()]
        if dept_list:
            query = query.filter(Staff.department.in_(dept_list))

    # 按部门筛选
    if department == "__none__":
        query = query.filter(Staff.department == None)
    elif department:
        query = query.filter(Staff.department == department)

    # 搜索
    if search:
        like_pattern = f"%{search}%"
        query = query.filter(
            Staff.employee_id.like(like_pattern) | Staff.name.like(like_pattern)
        )

    total = query.count()
    query = query.order_by(Staff.work_type, Staff.employee_id).offset(
        (page - 1) * page_size
    ).limit(page_size)
    return query.all(), total


def get_resigned_staff_list(
   db: Session,
   page: int = 1,
   page_size: int = 20,
   search: str | None = None,
   work_type: str | None = None,
   department_filter: str | None = None,
   work_type_filter: str | None = None,
   scope: str = "active",
) -> tuple[list[Staff], int, dict]:
   """获取离职人员列表（含保留期统计口径）

   [新增 2026-09-11] 离职保留期策略：
   - 离职未满 `RESIGN_RETENTION_DAYS`（默认 180 天 = 6 个月）→ 作为「在档离职人员」逐条展示，
     可查看详情、恢复在职；
   - 离职已满保留期 → **仅保留统计**（不再作为明细维护），由定时任务私信超管提醒
     手动删除其登录账号；如确需查看，可显式传 include_archived=True。
   - 历史数据兼容：resigned_at 为空时以 updated_at 作为离职时间近似值。

   返回 (items, total, stats)；stats 统计的是**过滤条件内**的口径。
   """
   eff_time = func.coalesce(Staff.resigned_at, Staff.updated_at)
   cutoff = utc_now() - timedelta(days=RESIGN_RETENTION_DAYS)

   base = db.query(Staff).filter(Staff.status == "resigned")

   # 工种筛选（用户主动选择）
   if work_type:
       base = base.filter(Staff.work_type == work_type)

   # 工种范围过滤（基于权限的强制限制，逗号分隔）
   if work_type_filter and not work_type:
       wt_list = [w.strip() for w in work_type_filter.split(",") if w.strip()]
       if wt_list:
           base = base.filter(Staff.work_type.in_(wt_list))

   # 按部门过滤（支持逗号分隔的多个部门名称）
   if department_filter:
       dept_list = [d.strip() for d in department_filter.split("||") if d.strip()]
       if dept_list:
           base = base.filter(Staff.department.in_(dept_list))

   if search:
       like_pattern = f"%{search}%"
       base = base.filter(
           Staff.employee_id.like(like_pattern) | Staff.name.like(like_pattern)
       )

   total_all = base.count()
   archived_count = base.filter(eff_time <= cutoff).count()

   query = base
   if scope == "archived":
       # 仅列「已满保留期」的离职人员（保留期策略下只计统计，供管理员清理登录账号）
       query = query.filter(eff_time <= cutoff)
   elif scope != "all":
       # 默认仅列「在档离职人员」：未满保留期，或历史数据无时间可依（保守地保留在明细中）
       query = query.filter(or_(eff_time > cutoff, eff_time.is_(None)))

   total = query.count()
   items = query.order_by(Staff.work_type, Staff.employee_id).offset(
       (page - 1) * page_size
   ).limit(page_size).all()

   stats = {
       "total": total_all,                    # 离职总人数
       "in_archive": total_all - archived_count,  # 在档（未满保留期）
       "archived": archived_count,            # 已满保留期（仅计入统计）
       "retention_days": RESIGN_RETENTION_DAYS,
       # [统一时间口径] 带 Z 的 UTC ISO，前端统一转本地时区
       "cutoff": to_iso_utc(cutoff),
       "scope": scope,
   }
   return items, total, stats


def get_staff(db: Session, employee_id: str) -> Staff | None:
    """按工号查询人员。

    [修复] 兼容工号含前后不可见字符（空格/制表符）的历史脏数据：
    1. 对输入工号 strip，避免前端/Excel 带入的空白导致查询失败；
    2. 精确匹配未命中时，兜底用 trim(employee_id) 比较（如 '\t900420'）。
    """
    key = (employee_id or "").strip()
    if not key:
        return None
    row = db.query(Staff).filter(Staff.employee_id == key).first()
    if row:
        return row
    # 兜底：忽略存储值的前后空白匹配，兼容历史脏数据
    return db.query(Staff).filter(func.trim(Staff.employee_id) == key).first()


# ==================== 新增 ====================

def create_staff(db: Session, staff_in: StaffCreate) -> Staff:
    data = staff_in.model_dump()
    # [修复] 创建时 strip employee_id，防止 Excel/手动输入带入前后空白
    data["employee_id"] = data.get("employee_id", "").strip()
    staff = Staff(**data)
    db.add(staff)
    db.flush()
    return staff


# ==================== 更新 ====================

def update_staff(db: Session, employee_id: str, staff_in: StaffUpdate, updated_by: str = None) -> Staff | None:
    key = (employee_id or "").strip()
    staff = get_staff(db, key)
    if not staff:
        return None
    update_data = staff_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(staff, field, value)
    staff.updated_by = updated_by
    staff.updated_at = utc_now()
    db.flush()
    return staff


# ==================== 删除 ====================

def delete_staff(db: Session, employee_id: str) -> bool:
    key = (employee_id or "").strip()
    staff = get_staff(db, key)
    if not staff:
        return False
    # 先删除关联的 user_department_scope 记录，避免 NOT NULL 约束冲突
    db.query(UserDepartmentScope).filter(
        UserDepartmentScope.employee_id == staff.employee_id
    ).delete(synchronize_session=False)
    db.delete(staff)
    db.flush()
    return True
