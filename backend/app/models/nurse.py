# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Nurse(Base):
    __tablename__ = "nurses"

    employee_id = Column(
        String(20),
        ForeignKey("users.employee_id", ondelete="CASCADE"),
        primary_key=True,
        comment="护士工号",
    )
    name = Column(String(50), nullable=False, comment="姓名")
    title = Column(String(50), comment="职称")
    position = Column(String(50), comment="职务")
    ward_area = Column(String(100), nullable=True, comment="所属病区")
    remarks = Column(Text, comment="备注")
    front_photo = Column(String(500), nullable=True, comment="正面形象照路径")
    side_photo = Column(String(500), nullable=True, comment="侧面形象照路径")
    status = Column(String(20), nullable=False, default="active", comment="状态: active-在职, resigned-离职")
    updated_by = Column(String(20), nullable=True, comment="最后修改人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="最后修改时间")

    # 关联用户信息（获取科室等）
    user = relationship("User", backref="nurse_info", lazy="joined")

    @property
    def department(self) -> str | None:
        """从关联的 User 获取科室"""
        return self.user.department if self.user else None
