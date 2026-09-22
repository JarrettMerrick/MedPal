# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""注册申请相关请求模型（登录页自助注册 / 审核）。"""

from pydantic import BaseModel, Field


class RegistrationSubmit(BaseModel):
    """提交注册申请（免登录接口入参）"""
    employee_id: str = Field(..., max_length=20, description="工号（登录账号）")
    name: str = Field(..., max_length=50, description="姓名")
    password: str = Field(..., max_length=50, description="密码")
    work_type: str = Field(..., max_length=20, description="工种: doctor/nurse/technician/admin")
    department: str = Field(..., max_length=100, description="所属科室名称")


class RegistrationReject(BaseModel):
    """驳回注册申请"""
    reason: str = Field(..., max_length=200, description="驳回原因（必填）")
