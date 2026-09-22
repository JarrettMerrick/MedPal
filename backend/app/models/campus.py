# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""
院区-楼栋-楼层-区域 信息维护模块

层级关系：院区 → 楼栋 → 楼层 → 区域
[调整 2026-09-12] 每个楼层可自由划分并绑定**多个**区域（例如东区可关联多个区域），
不再限制「一个楼层只能有一个区域」；area_type（east/west/merged）仅作为分类标签。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Campus(Base):
    """院区信息"""
    __tablename__ = "campuses"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="院区ID")
    name = Column(String(100), nullable=False, unique=True, comment="院区名称")
    description = Column(Text, nullable=True, comment="院区描述")
    address = Column(String(200), nullable=True, comment="院区地址")
    # [新增 2026-09-07] 院区代号：用于标识/平面图等场景的简短编码
    code = Column(String(50), nullable=True, comment="院区代号")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_by = Column(String(20), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=True, server_default=func.now(), comment="创建时间")
    updated_by = Column(String(20), nullable=True, comment="更新人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联楼栋
    buildings = relationship(
        "Building",
        back_populates="campus",
        cascade="all, delete-orphan",
        order_by="Building.building_number",
    )


class Building(Base):
    """楼栋信息"""
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="楼栋ID")
    campus_id = Column(
        Integer,
        ForeignKey("campuses.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属院区ID",
    )
    name = Column(String(100), nullable=False, comment="楼栋名称")
    building_number = Column(String(50), nullable=False, comment="楼栋编号")
    description = Column(Text, nullable=True, comment="楼栋描述")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_by = Column(String(20), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=True, server_default=func.now(), comment="创建时间")
    updated_by = Column(String(20), nullable=True, comment="更新人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联院区
    campus = relationship("Campus", back_populates="buildings")
    
    # 关联楼层
    floors = relationship(
        "Floor",
        back_populates="building",
        cascade="all, delete-orphan",
        order_by="Floor.floor_number",
    )


class Floor(Base):
    """楼层信息"""
    __tablename__ = "floors"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="楼层ID")
    building_id = Column(
        Integer,
        ForeignKey("buildings.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属楼栋ID",
    )
    # [调整 2026-09-17] 楼层号由整数改为字符串字母编号：
    #   地上 F1/F2/F3…（F3 = 三层）、地下 B1/B2/B3…（B1 = 地下一层）
    # 原实现为整数（负数表示地下），无法表达 B1/F3 这类字母编号。
    # 存量数字由启动时的幂等迁移 services/floor_number_migrator 转换为字母编号；
    # SQLite 类型亲和性宽松，旧库该列即使仍是 INTEGER 也能原样存储字符串，
    # 新库则由 create_all 直接建为 VARCHAR，无需手工改表。
    floor_number = Column(
        String(20), nullable=False,
        comment="楼层号：F1/F2…（地上）、B1/B2…（地下，B1 为地下一层）",
    )
    floor_name = Column(String(100), nullable=True, comment="楼层名称")
    description = Column(Text, nullable=True, comment="楼层描述")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_by = Column(String(20), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=True, server_default=func.now(), comment="创建时间")
    updated_by = Column(String(20), nullable=True, comment="更新人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联楼栋
    building = relationship("Building", back_populates="floors")
    
    # 关联区域
    areas = relationship(
        "Area",
        back_populates="floor",
        cascade="all, delete-orphan",
        order_by="Area.name",
    )


class Area(Base):
    """区域信息"""
    __tablename__ = "areas"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="区域ID")
    floor_id = Column(
        Integer,
        ForeignKey("floors.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属楼层ID",
    )
    name = Column(String(100), nullable=False, comment="区域名称")
    area_type = Column(String(20), nullable=False, default="merged", comment="区域类型: east/west/merged")
    description = Column(Text, nullable=True, comment="区域描述")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_by = Column(String(20), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=True, server_default=func.now(), comment="创建时间")
    updated_by = Column(String(20), nullable=True, comment="更新人")
    updated_at = Column(DateTime, nullable=True, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联楼层
    floor = relationship("Floor", back_populates="areas")