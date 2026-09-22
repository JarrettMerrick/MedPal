// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 文件库 API：设计文件的集中管理（分类 / 标签 / 版本 / 回收站 / 标准设计文件）。
 *
 * [新增 2026-09-17] 对应后端 routers/design_files.py 与 routers/file_taxonomy.py。
 * 预览与下载统一走后端鉴权接口（不使用 /uploads 静态直链）：
 * 前端以 blob 方式获取（见 utils/fileDownload.ts），确保始终携带访问令牌。
 */
import api, { uploadApi } from './client';

// ==================== 类型 ====================

export interface FileTag {
  id: number;
  name: string;
  /** 标签维度（分组名，如 项目 / 类型 / 状态） */
  group_name: string;
  color?: string | null;
  /** 使用该标签的文件数 */
  file_count: number;
  created_at?: string | null;
}

/**
 * 文件分类（**沿用「标识设置 → 标识分类」**，扁平结构，无层级）。
 *
 * [调整 2026-09-17] 原为文件库自建的树形分类（支持增删改）；
 * 现统一为标识分类：文件管理页**只读**，分类的增删改请前往
 * 「标识设置 → 标识分类」页面维护。
 */
export interface FileCategoryItem {
  id: number;
  name: string;
  /** 标识分类编码（如 DEPT_SIGN） */
  code: string;
  /** 标识分类颜色（十六进制，与平面图标记点同源） */
  color?: string | null;
  description?: string | null;
  /** 是否启用（禁用分类仍会返回：历史文件可能仍归属其中） */
  is_active: boolean;
  /** 该分类下的文件数 */
  file_count: number;
}

export type FilePreviewType = 'image' | 'pdf' | 'none';

export interface DesignFileItem {
  id: number;
  name: string;
  stored_path: string;
  file_ext?: string | null;
  file_size?: number | null;
  mime_type?: string | null;
  is_standard: boolean;
  category_id?: number | null;
  category_name?: string | null;
  tags: FileTag[];
  remark?: string | null;
  uploader_id?: string | null;
  uploader_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  current_version: number;
  version_count: number;
  /** 被标识引用数（引用共享；>0 时禁止删除） */
  ref_count: number;
  is_deleted: boolean;
  deleted_at?: string | null;
  deleted_by?: string | null;
  preview_type: FilePreviewType;
  thumbnail_path?: string | null;
}

export interface DesignFileVersion {
  id: number;
  version: number;
  stored_path: string;
  file_ext?: string | null;
  file_size?: number | null;
  note?: string | null;
  uploaded_by?: string | null;
  uploaded_by_name?: string | null;
  created_at?: string | null;
}

export interface DesignFileReference {
  signage_id: number;
  code?: string | null;
  name?: string | null;
  status?: string | null;
}

export interface DesignFileDetail extends DesignFileItem {
  versions: DesignFileVersion[];
  references: DesignFileReference[];
}

export interface DesignFileListParams {
  page?: number;
  page_size?: number;
  keyword?: string;
  category_id?: number;
  include_subcategory?: boolean;
  tag_ids?: number[];
  start_date?: string;
  end_date?: string;
  is_standard?: boolean;
  uncategorized?: boolean;
  only_deleted?: boolean;
}

export interface DesignFileListResponse {
  total: number;
  page: number;
  page_size: number;
  items: DesignFileItem[];
}

export interface DesignFileSummary {
  total: number;
  standard: number;
  trashed: number;
  uncategorized: number;
  total_size: number;
}

export interface StandardFileOption {
  id: number;
  name: string;
  stored_path: string;
  file_ext?: string | null;
  category_name?: string | null;
  tags: FileTag[];
  preview_type: FilePreviewType;
  thumbnail_path?: string | null;
  ref_count: number;
}

export interface BatchBlockedItem {
  id: number;
  name: string;
  ref_count: number;
}

// ==================== 文件 ====================

/** 分页检索文件（关键词 / 分类 / 标签 / 时间 / 标准标记 / 回收站） */
export const listDesignFiles = (params: DesignFileListParams): Promise<DesignFileListResponse> =>
  api.get('/files', {
    params: {
      ...params,
      // 后端以逗号分隔字符串接收标签，便于 GET 缓存友好
      tag_ids: params.tag_ids?.length ? params.tag_ids.join(',') : undefined,
    },
  }).then((r) => r.data);

/** 文件库概览（总数 / 标准数 / 未分类 / 回收站 / 占用空间） */
export const getDesignFileSummary = (): Promise<DesignFileSummary> =>
  api.get('/files/summary').then((r) => r.data);

/**
 * 标准设计文件选项（标识表单「从标准库选择」）。
 *
 * [新增 2026-09-17] category_name：标识表单传入**自身分类名**，
 * 只返回同分类的标准设计文件，实现「只能引用同分类文件」的约束。
 */
export const getStandardFileOptions = (params?: {
  keyword?: string; category_id?: number; category_name?: string;
}): Promise<{ items: StandardFileOption[] }> =>
  api.get('/files/standard-options', { params }).then((r) => r.data);

/** 文件详情（含版本历史与引用该文件的标识清单） */
export const getDesignFile = (id: number): Promise<DesignFileDetail> =>
  api.get(`/files/${id}`).then((r) => r.data);

/** 上传文件到文件库（支持多选，单个失败不影响其余） */
export const uploadDesignFiles = (
  files: File[],
  options?: { category_id?: number; is_standard?: boolean; remark?: string },
): Promise<{ created: { id: number; name: string; file_ext?: string }[]; errors: { filename?: string; detail: string }[]; total: number }> => {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  if (options?.category_id) formData.append('category_id', String(options.category_id));
  if (options?.is_standard) formData.append('is_standard', 'true');
  if (options?.remark) formData.append('remark', options.remark);
  return uploadApi.post('/files/upload', formData).then((r) => r.data);
};

/** 更新文件元数据（名称 / 分类 / 标准标记 / 备注 / 标签） */
export const updateDesignFile = (
  id: number,
  payload: {
    name?: string;
    category_id?: number | null;
    is_standard?: boolean;
    remark?: string;
    tag_ids?: number[];
  },
): Promise<DesignFileDetail> => api.patch(`/files/${id}`, payload).then((r) => r.data);

/** 移入回收站（软删；被标识引用时后端拒绝） */
export const deleteDesignFile = (id: number): Promise<{ ok: boolean; deleted: number }> =>
  api.delete(`/files/${id}`).then((r) => r.data);

/** 从回收站恢复 */
export const restoreDesignFile = (id: number): Promise<{ ok: boolean; restored: number }> =>
  api.post(`/files/${id}/restore`).then((r) => r.data);

/** 彻底删除（清理物理文件；被引用时后端拒绝） */
export const purgeDesignFile = (id: number): Promise<{ ok: boolean; purged: number }> =>
  api.delete(`/files/${id}/purge`).then((r) => r.data);

/** 上传新版本（旧版本留档，引用该文件的标识会自动指向新版本） */
export const uploadDesignFileVersion = (
  id: number, file: File, note?: string,
): Promise<DesignFileDetail> => {
  const formData = new FormData();
  formData.append('file', file);
  if (note) formData.append('note', note);
  return uploadApi.post(`/files/${id}/versions`, formData).then((r) => r.data);
};

/** 回滚到指定版本 */
export const restoreDesignFileVersion = (id: number, versionId: number): Promise<DesignFileDetail> =>
  api.post(`/files/${id}/versions/${versionId}/restore`).then((r) => r.data);

/** 文件预览接口地址（需以 blob 方式请求，见 utils/fileDownload.ts） */
export const designFilePreviewPath = (id: number): string => `/files/${id}/preview`;

/** 文件下载接口地址 */
export const designFileDownloadPath = (id: number): string => `/files/${id}/download`;

// ==================== 批量操作 ====================

/** 批量移动分类 */
export const batchSetCategory = (ids: number[], categoryId: number | null):
Promise<{ ok: boolean; updated: number }> =>
  api.post('/files/batch/category', { ids, category_id: categoryId }).then((r) => r.data);

/** 批量标记 / 取消标准设计文件 */
export const batchSetStandard = (ids: number[], isStandard: boolean):
Promise<{ ok: boolean; updated: number }> =>
  api.post('/files/batch/standard', { ids, is_standard: isStandard }).then((r) => r.data);

/** 批量打标签 / 移除标签 */
export const batchSetTags = (ids: number[], addTagIds: number[], removeTagIds: number[]):
Promise<{ ok: boolean; added: number; removed: number }> =>
  api.post('/files/batch/tags', { ids, add_tag_ids: addTagIds, remove_tag_ids: removeTagIds })
    .then((r) => r.data);

/** 批量移入回收站（被引用的文件会被跳过并在 blocked 中返回） */
export const batchDeleteFiles = (ids: number[]):
Promise<{ ok: boolean; deleted: number; blocked: BatchBlockedItem[] }> =>
  api.post('/files/batch/delete', { ids }).then((r) => r.data);

/** 批量从回收站恢复 */
export const batchRestoreFiles = (ids: number[]): Promise<{ ok: boolean; restored: number }> =>
  api.post('/files/batch/restore', { ids }).then((r) => r.data);

/** 批量彻底删除 */
export const batchPurgeFiles = (ids: number[]):
Promise<{ ok: boolean; purged: number; blocked: BatchBlockedItem[] }> =>
  api.post('/files/batch/purge', { ids }).then((r) => r.data);

/** 从 Content-Disposition 解析下载文件名（兼容 RFC 5987 的 filename*=UTF-8''） */
function parseDispositionFilename(disposition?: string): string {
  if (!disposition) return '';
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      // 编码异常时退回下面的普通 filename
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain?.[1] || '';
}

/**
 * 批量打包下载（zip：按分类建目录，文件名用文件管理中的「使用名」）。
 *
 * [新增 2026-09-17] 需求（方案 A）：勾选文件一键打包下载。
 * 注意：「标识导出」的附件包是按**标识**维度打包的（筛选 signages.category），
 * 无法导出未被任何标识引用的文件库文件，因此这里在文件库侧单独提供打包能力。
 *
 * 返回 { blob, packed, skipped, filename }，由调用方触发浏览器下载；
 * skipped 表示记录存在但磁盘文件缺失（已在 zip 中跳过）。
 */
export const downloadFilesZip = (
  ids: number[],
): Promise<{ blob: Blob; packed: number; skipped: number; filename: string }> =>
  api.post('/files/batch/download', { ids }, { responseType: 'blob' }).then((r) => ({
    blob: r.data as Blob,
    packed: Number(r.headers['x-packed-count'] ?? 0),
    skipped: Number(r.headers['x-skipped-count'] ?? 0),
    filename: parseDispositionFilename(r.headers['content-disposition']) || '文件库.zip',
  }));

// ==================== 分类（只读，数据源为标识分类） ====================

/**
 * 分类列表（含每个分类下的文件数）。
 *
 * [调整 2026-09-17] 数据源为「标识设置 → 标识分类」（扁平结构）。
 * 文件管理页**不提供分类的增删改入口**：维护请前往标识分类设置页
 * （/signage-categories，需 signage.category 权限）。
 */
export const listFileCategories = (): Promise<{ items: FileCategoryItem[] }> =>
  api.get('/file-categories').then((r) => r.data);

// ==================== 标签 ====================

/** 全部标签（可按维度过滤），含使用计数 */
export const listFileTags = (groupName?: string): Promise<{ items: FileTag[] }> =>
  api.get('/file-tags', { params: groupName ? { group_name: groupName } : undefined })
    .then((r) => r.data);

export const createFileTag = (payload: {
  name: string; group_name?: string; color?: string;
}): Promise<FileTag> => api.post('/file-tags', payload).then((r) => r.data);

export const updateFileTag = (
  id: number, payload: { name?: string; group_name?: string; color?: string },
): Promise<FileTag> => api.patch(`/file-tags/${id}`, payload).then((r) => r.data);

export const deleteFileTag = (id: number): Promise<{ ok: boolean }> =>
  api.delete(`/file-tags/${id}`).then((r) => r.data);
