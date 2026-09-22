# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="科室ID")
    name = Column(String(100), nullable=False, unique=True, comment="科室名称")
    category = Column(String(20), nullable=False, default="临床专科", comment="分类: 临床专科/护理病区/行政科室")
    description = Column(Text, nullable=True, comment="科室介绍")
    group_photo = Column(String(500), nullable=True, comment="科室合照路径")
    # [修复 2026-09-01] 新增 allowed_work_types 字段，支持混合科室（如行政科室容纳多种工种）
    # 逗号分隔工种列表，为空则按 category 默认规则；非空则只允许列表中的工种
    allowed_work_types = Column(String(100), nullable=True, comment="允许的工种列表，逗号分隔，为空则按类别默认规则")
    updated_by = Column(String(20), nullable=True, comment="最后修改人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="最后修改时间")

    # 关联特色技术
    specialties = relationship(
        "DepartmentSpecialty",
        back_populates="department",
        cascade="all, delete-orphan",
        order_by="DepartmentSpecialty.sort_order",
    )

    # 关联特色设备
    equipments = relationship(
        "DepartmentEquipment",
        back_populates="department",
        cascade="all, delete-orphan",
        order_by="DepartmentEquipment.sort_order",
    )


class DepartmentSpecialty(Base):
    __tablename__ = "department_specialties"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="特色技术ID")
    department_id = Column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属科室ID",
    )
    name = Column(String(200), nullable=False, comment="特色技术名称")
    detail = Column(Text, nullable=True, comment="详细简介")
    caption = Column(String(20), nullable=True, comment="技术卡片备注（导入/导出用）")
    sort_order = Column(Integer, default=0, comment="排序")

    department = relationship("Department", back_populates="specialties")

    # 关联特色技术图片
    images = relationship(
        "SpecialtyImage",
        back_populates="specialty",
        cascade="all, delete-orphan",
        order_by="SpecialtyImage.sort_order",
    )


class SpecialtyImage(Base):
    __tablename__ = "specialty_images"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="图片ID")
    specialty_id = Column(
        Integer,
        ForeignKey("department_specialties.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属特色技术ID",
    )
    image_url = Column(String(500), nullable=False, comment="图片路径")
    caption = Column(String(20), nullable=True, comment="图片备注文案")
    sort_order = Column(Integer, default=0, comment="排序")

    specialty = relationship("DepartmentSpecialty", back_populates="images")


class DepartmentEquipment(Base):
    __tablename__ = "department_equipments"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="设备ID")
    department_id = Column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属科室ID",
    )
    name = Column(String(200), nullable=False, comment="设备名称")
    model = Column(String(100), nullable=True, comment="设备型号")
    function_description = Column(Text, nullable=True, comment="功能描述")
    features = Column(Text, nullable=True, comment="设备特点")
    caption = Column(String(20), nullable=True, comment="设备卡片备注（导入/导出用）")
    sort_order = Column(Integer, default=0, comment="排序")

    department = relationship("Department", back_populates="equipments")

    # 关联设备图片
    images = relationship(
        "EquipmentImage",
        back_populates="equipment",
        cascade="all, delete-orphan",
        order_by="EquipmentImage.sort_order",
    )


class EquipmentImage(Base):
    __tablename__ = "equipment_images"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="图片ID")
    equipment_id = Column(
        Integer,
        ForeignKey("department_equipments.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属设备ID",
    )
    image_url = Column(String(500), nullable=False, comment="图片路径")
    caption = Column(String(20), nullable=True, comment="图片备注文案")
    sort_order = Column(Integer, default=0, comment="排序")

    equipment = relationship("DepartmentEquipment", back_populates="images")
