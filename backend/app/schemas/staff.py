# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# 工种常量
WORK_TYPE_DOCTOR = "doctor"
WORK_TYPE_NURSE = "nurse"  
WORK_TYPE_TECHNICIAN = "technician"
WORK_TYPE_ADMIN = "admin"

WORK_TYPES = [WORK_TYPE_DOCTOR, WORK_TYPE_NURSE, WORK_TYPE_TECHNICIAN, WORK_TYPE_ADMIN]

WORK_TYPE_LABELS = {
    WORK_TYPE_DOCTOR: "医生",
    WORK_TYPE_NURSE: "护士",
    WORK_TYPE_TECHNICIAN: "技师",
    WORK_TYPE_ADMIN: "行政",
}


class StaffCreate(BaseModel):
    """新增人员"""
    employee_id: str = Field(..., pattern=r"^\d{6}$", description="工号，必须为6位数字")
    name: str = Field(..., description="姓名")
    work_type: str = Field(..., description="工种: doctor/nurse/technician/admin")
    education: str | None = None
    title: str | None = None
    department: str = Field(..., description="所属科室/病区/部门")
    position: str | None = None
    expertise_short: str | None = None
    expertise_standard: str | None = None
    social_appointments: str | None = None
    honors: str | None = None
    remarks: str | None = None


class StaffUpdate(BaseModel):
    """更新人员"""
    name: str | None = None
    work_type: str | None = None
    education: str | None = None
    title: str | None = None
    department: str | None = None
    position: str | None = None
    expertise_short: str | None = None
    expertise_standard: str | None = None
    social_appointments: str | None = None
    honors: str | None = None
    remarks: str | None = None
    front_photo: str | None = None
    side_photo: str | None = None


class StaffResponse(BaseModel):
    """人员响应"""
    employee_id: str
    name: str
    work_type: str
    education: str | None = None
    title: str | None = None
    department: str | None = None
    position: str | None = None
    expertise_short: str | None = None
    expertise_standard: str | None = None
    social_appointments: str | None = None
    honors: str | None = None
    remarks: str | None = None
    front_photo: str | None = None
    side_photo: str | None = None
    status: str = "active"
    # [新增 2026-09-11] 离职档案（仅离职人员有值）
    resigned_at: Optional[datetime] = None
    resign_reason: Optional[str] = None
    resigned_by: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    # [新增 2026-09-11] 待审核变更提示（无待审时为 None）：
    # {count, level_label, change_summary, changed_labels, submitted_by_name, submitted_at, escalated}
    # 用于在人员列表/详情**显著位置**提示「科室负责人未审核」。
    pending_change: Optional[dict] = None

    class Config:
        from_attributes = True


class StaffListResponse(BaseModel):
    """人员列表响应"""
    total: int
    items: list[StaffResponse]
    page: int
    page_size: int
    # [新增 2026-09-11] 离职人员列表的保留期统计口径
    # {total 离职总数, in_archive 在档(未满保留期), archived 已满保留期仅计统计, retention_days, cutoff}
    stats: Optional[dict] = None


class StaffVerifyItem(BaseModel):
    """数据核对项（用于筛选信息未填写完整的人员）"""
    employee_id: str
    name: str
    work_type: str
    department: str | None = None
    # 缺失字段代码列表，取值: name-姓名, title-职称, expertise-专业擅长, photo-个人照片, card-卡片照片
    missing_fields: list[str] = []
    # 缺失字段中文标签列表（如 ["职称", "专业擅长", "个人照片"]）
    missing_labels: list[str] = []


class StaffVerifyResponse(BaseModel):
    """数据核对结果"""
    total: int
    missing_total: int
    items: list[StaffVerifyItem]
    page: int
    page_size: int
