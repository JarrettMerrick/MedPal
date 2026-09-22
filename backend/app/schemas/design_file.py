# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""文件库数据模式定义（设计文件的集中管理）。

[新增 2026-09-17] 对应 models/design_file.py 的五张表：
    分类（树）、标签（按维度分组）、文件、文件-标签、版本历史。
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def _coerce_single_value(value):
    """[修复 2026-09-17] 把「单元素数组」归一为字符串。

    背景：前端 antd Select 的 mode="tags"（标签维度选择）会提交数组
    （如 {"group_name": ["项目"]}），而后端字段声明为 str，
    Pydantic 会在校验阶段直接返回 422，业务代码没有机会处理。

    这里在 mode="before" 阶段取首元素，兼容旧版前端缓存与第三方脚本调用；
    字符串输入原样返回，无副作用。
    """
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return value


# ==================== 分类 ====================
# [调整 2026-09-17] 文件分类已统一为「标识设置 → 标识分类」（signage_categories）：
# 只读列表由 GET /api/file-categories 返回（见 services/file_taxonomy_service.build_category_list），
# 分类的增删改使用标识分类接口 /api/signage-categories（标识分类设置页）。
# 原 FileCategoryBase / FileCategoryCreate / FileCategoryUpdate / FileCategoryNode 已移除。


# ==================== 标签（按维度分组） ====================

class FileTagBase(BaseModel):
    """标签基础信息"""
    name: str = Field(..., max_length=50, description="标签名")
    group_name: str = Field("通用", max_length=50, description="标签维度（分组名，如 项目/类型/状态）")
    color: Optional[str] = Field(None, max_length=20, description="标签颜色（十六进制，可空）")

    @field_validator("name", "group_name", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        """[修复 2026-09-17] 兼容数组入参（前端 Select mode="tags" 提交 ["项目"]）"""
        return _coerce_single_value(value)


class FileTagCreate(FileTagBase):
    """创建标签"""
    pass


class FileTagUpdate(BaseModel):
    """更新标签"""
    name: Optional[str] = Field(None, max_length=50, description="标签名")
    group_name: Optional[str] = Field(None, max_length=50, description="标签维度")
    color: Optional[str] = Field(None, max_length=20, description="标签颜色")

    @field_validator("name", "group_name", mode="before")
    @classmethod
    def _coerce_text(cls, value):
        """[修复 2026-09-17] 兼容数组入参（同 FileTagBase）"""
        return _coerce_single_value(value)


class FileTagOut(FileTagBase):
    """标签输出（含使用计数）"""
    id: int = Field(..., description="标签ID")
    file_count: int = Field(0, description="使用该标签的文件数")
    created_at: Optional[datetime] = Field(None, description="创建时间")

    class Config:
        from_attributes = True


# ==================== 文件 ====================

class DesignFileUpdate(BaseModel):
    """更新文件元数据（字段可选，未传表示不修改）"""
    name: Optional[str] = Field(None, max_length=200, description="显示名")
    category_id: Optional[int] = Field(None, description="所属分类（0 或 null 表示移出分类）")
    is_standard: Optional[bool] = Field(None, description="是否标准设计文件")
    remark: Optional[str] = Field(None, description="备注")
    tag_ids: Optional[List[int]] = Field(
        None, description="标签ID列表（传了即全量替换；传空数组表示清空标签）",
    )


class DesignFileVersionOut(BaseModel):
    """版本记录"""
    id: int = Field(..., description="版本记录ID")
    version: int = Field(..., description="版本号")
    stored_path: str = Field(..., description="该版本物理文件相对路径")
    file_ext: Optional[str] = Field(None, description="扩展名")
    file_size: Optional[int] = Field(None, description="文件大小（字节）")
    note: Optional[str] = Field(None, description="版本说明")
    uploaded_by: Optional[str] = Field(None, description="上传人工号")
    uploaded_by_name: Optional[str] = Field(None, description="上传人姓名")
    created_at: Optional[datetime] = Field(None, description="版本创建时间")

    class Config:
        from_attributes = True


class DesignFileReference(BaseModel):
    """文件被引用情况（哪条标识在使用该文件）"""
    signage_id: int = Field(..., description="标识ID")
    code: Optional[str] = Field(None, description="标识编码")
    name: Optional[str] = Field(None, description="标识名称")
    status: Optional[str] = Field(None, description="标识状态")


class DesignFileBrief(BaseModel):
    """文件列表项"""
    id: int = Field(..., description="文件ID")
    name: str = Field(..., description="显示名")
    stored_path: str = Field(..., description="物理文件相对路径")
    file_ext: Optional[str] = Field(None, description="扩展名")
    file_size: Optional[int] = Field(None, description="文件大小（字节）")
    mime_type: Optional[str] = Field(None, description="MIME 类型")
    is_standard: bool = Field(False, description="是否标准设计文件")
    category_id: Optional[int] = Field(None, description="所属分类ID")
    category_name: Optional[str] = Field(None, description="所属分类名称")
    tags: List[FileTagOut] = Field(default_factory=list, description="标签列表")
    remark: Optional[str] = Field(None, description="备注")
    uploader_id: Optional[str] = Field(None, description="上传人工号")
    uploader_name: Optional[str] = Field(None, description="上传人姓名")
    created_at: Optional[datetime] = Field(None, description="上传时间")
    updated_at: Optional[datetime] = Field(None, description="最后修改时间")
    current_version: int = Field(1, description="当前版本号")
    version_count: int = Field(1, description="版本总数")
    ref_count: int = Field(0, description="被标识引用数（引用共享）")
    is_deleted: bool = Field(False, description="是否在回收站")
    deleted_at: Optional[datetime] = Field(None, description="删除时间")
    deleted_by: Optional[str] = Field(None, description="删除人工号")
    # 可预览类型：image（图片）/ pdf（浏览器内预览）/ none（仅下载）
    preview_type: str = Field("none", description="预览类型：image / pdf / none")
    thumbnail_path: Optional[str] = Field(None, description="缩略图相对路径（图片类型）")


class DesignFileDetail(DesignFileBrief):
    """文件详情（含版本与引用）"""
    versions: List[DesignFileVersionOut] = Field(default_factory=list, description="版本列表")
    references: List[DesignFileReference] = Field(default_factory=list, description="引用该文件的标识")


class DesignFileListResponse(BaseModel):
    """文件列表响应"""
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页")
    page_size: int = Field(..., description="每页条数")
    items: List[DesignFileBrief] = Field(default_factory=list, description="文件列表")


class BatchIdsRequest(BaseModel):
    """批量操作：目标 ID 列表"""
    ids: List[int] = Field(..., min_length=1, description="文件ID列表")


class BatchCategoryRequest(BatchIdsRequest):
    """批量修改分类"""
    category_id: Optional[int] = Field(None, description="目标分类ID（为空表示移出分类）")


class BatchTagsRequest(BatchIdsRequest):
    """批量打标签"""
    add_tag_ids: List[int] = Field(default_factory=list, description="新增的标签ID")
    remove_tag_ids: List[int] = Field(default_factory=list, description="移除的标签ID")


class BatchStandardRequest(BatchIdsRequest):
    """批量标记标准设计文件"""
    is_standard: bool = Field(..., description="是否标记为标准设计文件")


class DesignFileStandardOption(BaseModel):
    """标准设计文件选择项（标识表单「从标准库选择」用）"""
    id: int = Field(..., description="文件ID")
    name: str = Field(..., description="显示名")
    stored_path: str = Field(..., description="物理文件相对路径")
    file_ext: Optional[str] = Field(None, description="扩展名")
    category_name: Optional[str] = Field(None, description="所属分类名称")
    tags: List[FileTagOut] = Field(default_factory=list, description="标签列表")
    preview_type: str = Field("none", description="预览类型")
    thumbnail_path: Optional[str] = Field(None, description="缩略图相对路径")
    ref_count: int = Field(0, description="已被引用次数")
