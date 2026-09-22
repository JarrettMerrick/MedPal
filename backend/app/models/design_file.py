# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""文件库模型：标识设计文件的集中管理（分类 / 标签 / 版本 / 回收站）。

[新增 2026-09-17] 需求：标识管理下新增「文件管理」菜单，集中管理所有已上传的设计文件，
并内置「标准设计文件」标记 —— 被标记后，上传标识设计文件时可直接搜索选择复用。

设计骨架参考成熟开源方案（ResourceSpace / Pimcore DAM / Eagle 素材管理）的通用分层：
    资产层  DesignFile         文件元数据 + 物理路径 + 标准标记 + 软删（回收站）
    组织层  SignageCategory    分类**沿用「标识设置 → 标识分类」**（signage_categories，扁平）
            FileTag            标签（按 group_name 分维度：项目 / 类型 / 状态…）
    版本层  DesignFileVersion  同一文件的历次版本留档（可回滚）
    引用层  signages.design_file_id  标识与文件为「引用共享」关系：
           多条标识可复用同一份标准设计文件（磁盘只存一份），
           删除文件时按引用数保护，避免影响在用标识。

[调整 2026-09-17] 分类口径统一：原文件库自建的树形分类（file_categories 表 +
增删改入口）已移除，文件分类直接引用标识分类，避免两处维护不一致；
文件管理页不再提供分类的增删改入口，维护统一在「标识设置 → 标识分类」页面。
（file_categories 表本身保留在数据库中，不做破坏性删表。）

约定：
- 软删：DesignFile.is_deleted = True 表示已进回收站，列表默认不展示，可恢复或彻底删除；
- 彻底删除时才清理磁盘物理文件（含 thumb_/orig_ 派生文件）。
"""

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func, Index,
)
from sqlalchemy.orm import relationship

from app.database import Base


class FileTag(Base):
    """文件标签（按 group_name 分维度，如「项目」「类型」「状态」）。"""

    __tablename__ = "file_tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, comment="标签名")
    # 标签维度：便于按「项目 / 类型 / 状态」等多维度归集与筛选（同一维度内可多选）
    group_name = Column(String(50), nullable=False, default="通用", comment="标签维度（分组名）")
    color = Column(String(20), nullable=True, comment="标签颜色（十六进制，可空）")
    created_by = Column(String(20), nullable=True, comment="创建人工号")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")

    __table_args__ = (
        # 同一维度内不允许重名（不同维度可同名）
        Index("uq_file_tags_group_name", "group_name", "name", unique=True),
    )


class DesignFile(Base):
    """设计文件（文件库主表）。"""

    __tablename__ = "design_files"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, comment="显示名（默认取上传时的原始文件名）")
    # 相对 uploads 根目录的路径，如 signage/南-XX-0-001_design_20260917_101530_ab12cd34.ai
    stored_path = Column(String(500), nullable=False, comment="物理文件相对路径")
    file_ext = Column(String(20), nullable=True, comment="扩展名（小写，含点）")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    mime_type = Column(String(100), nullable=True, comment="MIME 类型")

    # 标准设计文件标记：标识表单可搜索选择（引用共享）
    is_standard = Column(Boolean, default=False, index=True, comment="是否标准设计文件")

    # [调整 2026-09-17] 分类改为引用「标识设置 → 标识分类」（signage_categories），
    # 原外键指向文件库自建的 file_categories 表，已统一口径
    category_id = Column(
        Integer, ForeignKey("signage_categories.id"), nullable=True, index=True,
        comment="所属分类（标识分类ID，可为空 = 未分类）",
    )

    content_hash = Column(String(64), nullable=True, index=True, comment="内容哈希（SHA256，去重与变更识别）")
    remark = Column(Text, nullable=True, comment="备注")

    # 回收站（软删）：默认列表不展示，可恢复；彻底删除时才清理物理文件
    is_deleted = Column(Boolean, default=False, index=True, comment="是否已删除（回收站）")
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")
    deleted_by = Column(String(20), nullable=True, comment="删除人工号")

    uploader_id = Column(String(20), nullable=True, comment="上传人工号")
    uploader_name = Column(String(50), nullable=True, comment="上传人姓名")
    created_at = Column(DateTime, server_default=func.now(), comment="上传时间")
    updated_by = Column(String(20), nullable=True, comment="最后修改人工号")
    updated_at = Column(DateTime, onupdate=func.now(), comment="最后修改时间")

    # [调整 2026-09-17] 关联标识分类（同一份分类口径，见文件头说明）
    category = relationship("SignageCategory", foreign_keys=[category_id])
    tags = relationship(
        "DesignFileTag",
        back_populates="design_file",
        cascade="all, delete-orphan",
    )
    versions = relationship(
        "DesignFileVersion",
        back_populates="design_file",
        cascade="all, delete-orphan",
        order_by="DesignFileVersion.version.desc()",
    )


class DesignFileTag(Base):
    """文件-标签关联（多对多）。"""

    __tablename__ = "design_file_tags"

    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("design_files.id"), nullable=False, index=True)
    tag_id = Column(Integer, ForeignKey("file_tags.id"), nullable=False, index=True)

    design_file = relationship("DesignFile", back_populates="tags")
    tag = relationship("FileTag")

    __table_args__ = (
        Index("uq_design_file_tags", "file_id", "tag_id", unique=True),
    )


class DesignFileVersion(Base):
    """设计文件版本历史（同一文件保留历次上传的版本，可回滚为当前版本）。"""

    __tablename__ = "design_file_versions"

    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("design_files.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, comment="版本号（自增：1、2、3…）")
    stored_path = Column(String(500), nullable=False, comment="该版本物理文件相对路径")
    file_ext = Column(String(20), nullable=True, comment="扩展名")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    note = Column(String(200), nullable=True, comment="版本说明（如「初版」「按甲方意见修改」）")
    uploaded_by = Column(String(20), nullable=True, comment="上传人工号")
    uploaded_by_name = Column(String(50), nullable=True, comment="上传人姓名")
    created_at = Column(DateTime, server_default=func.now(), comment="版本创建时间")

    design_file = relationship("DesignFile", back_populates="versions")
