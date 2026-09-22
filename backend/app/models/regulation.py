# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class RegulationCategory(Base):
    __tablename__ = "regulation_categories"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="类别ID")
    name = Column(String(100), nullable=False, unique=True, comment="类别名称")
    # [新增] 类别代码：3位大写英文字母，唯一标识（用于制度牌编号/分类检索）
    code = Column(String(3), nullable=True, unique=True, comment="类别代码（3位大写英文字母）")
    sort_order = Column(Integer, default=0, comment="排序")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")

    regulations = relationship("Regulation", back_populates="category_rel")


class Regulation(Base):
    __tablename__ = "regulations"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="制度ID")
    name = Column(String(200), nullable=False, comment="制度名称")
    category_id = Column(Integer, ForeignKey("regulation_categories.id"), nullable=True, comment="所属类别ID")
    category_name = Column(String(100), nullable=True, comment="所属类别名称（冗余，方便查询）")
    version = Column(String(50), nullable=True, comment="制度版本")
    content = Column(Text, nullable=True, comment="制度内容")
    created_by = Column(String(20), nullable=True, comment="创建人")
    updated_by = Column(String(20), nullable=True, comment="最后修改人")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="最后修改时间")

    category_rel = relationship("RegulationCategory", back_populates="regulations")
    history = relationship(
        "RegulationHistory",
        back_populates="regulation",
        cascade="all, delete-orphan",
        order_by="RegulationHistory.edited_at.desc()",
    )


class RegulationHistory(Base):
    __tablename__ = "regulation_history"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="历史记录ID")
    regulation_id = Column(Integer, ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False, comment="制度ID")
    version = Column(String(50), nullable=True, comment="版本号（如 V01_BSM_260807）")
    content = Column(Text, nullable=True, comment="该版本制度内容快照")
    edited_by = Column(String(20), nullable=True, comment="修改人")
    edited_at = Column(DateTime, server_default=func.now(), comment="修改时间")
    change_summary = Column(Text, nullable=True, comment="修改摘要")

    regulation = relationship("Regulation", back_populates="history")
