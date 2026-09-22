// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api, { uploadApi } from './client';
// [修正 2026-09-22] 统一的 Blob 下载（替代本文件原先自带的同名实现）
import { downloadBlob } from '../utils/fileUtils';

// ==================== 导出 ====================

export const exportStaff = (params?: { work_type?: string; department?: string; status?: string; fields?: string }) =>
  api.get('/data/export/staff', { params, responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, '人员信息.xlsx');
  });

export const exportDepartments = () =>
  api.get('/data/export/departments', { responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, '科室信息.xlsx');
  });

export const exportRegulations = () =>
  api.get('/data/export/regulations', { responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, '制度信息.xlsx');
  });

// ==================== 导入模板 ====================

export const templateStaff = () =>
  api.get('/data/template/staff', { responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, '员工导入模板.xlsx');
  });

export const templateDepartments = () =>
  api.get('/data/template/departments', { responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, '科室导入模板.xlsx');
  });

export const templateRegulations = () =>
  api.get('/data/template/regulations', { responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, '制度导入模板.xlsx');
  });

// ==================== 导入 ====================

export interface ImportResult {
  message: string;
  added: number;
  skipped: number;
  details?: { row: number; employee_id?: string; name?: string; status: string; reason?: string }[];
  warnings?: string[];
}

/**
 * [改进] 导入接口统一走 uploadApi（300s 长超时）并支持上传进度回调：
 * 原 api 实例 10s 超时，大文件/大数据量导入超过 10s 会被前端中断，
 * 但后端仍在处理并写库，用户误以为失败而重复提交，导致并发写库崩溃。
 * onProgress 仅反映「文件上传到服务器」阶段进度（0-100），
 * 上传完成后进入后端解析+写库阶段（前端无法获取真实行进度）。
 */
export const importStaff = (file: File, onProgress?: (percent: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  return uploadApi.post<ImportResult>('/data/import/staff', fd, {
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)); },
  }).then((r) => r.data);
};

export const importDepartments = (file: File, onProgress?: (percent: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  return uploadApi.post('/data/import/departments', fd, {
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)); },
  }).then((r) => r.data);
};

export const importRegulations = (file: File, onProgress?: (percent: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  return uploadApi.post<{ message: string; added: number; skipped: number }>('/data/import/regulations', fd, {
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)); },
  }).then((r) => r.data);
};

export interface PhotoImportResult {
  message: string;
  imported: number;
  skipped: number;
  errors: string[];
}

export const importPhotos = (file: File, onProgress?: (percent: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  return uploadApi.post<PhotoImportResult>('/data/import/photos', fd, {
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)); },
  }).then((r) => r.data);
};

// ==================== 数据核对 ====================

export interface StaffVerifyItem {
  employee_id: string;
  name: string;
  work_type: 'doctor' | 'nurse' | 'technician' | 'admin';
  department: string | null;
  /**
   * 缺失字段代码:
   * name-姓名, title-职称,
   * expertise_short-专业擅长（短）, expertise_standard-专业擅长（标准）(仅医生),
   * photo-个人照片, card-卡片照片
   * 注：护士/技师不审核专业擅长。
   */
  missing_fields: string[];
  /** 缺失字段中文标签（如 ["职称", "专业擅长（短）", "个人照片"]） */
  missing_labels: string[];
}

export interface StaffVerifyResponse {
  total: number;
  missing_total: number;
  items: StaffVerifyItem[];
  page: number;
  page_size: number;
}

/**
 * 数据核对：筛选出信息未填写完整的人员（医生/护士/技师）。
 * [修复 2026-09-02] 数据核对功能：医生核对 姓名/职称/专业擅长（短）/专业擅长（标准）/个人照片/卡片照片，
 * 护士、技师核对 姓名/职称/照片/卡片照片（照片即正面形象照 front_photo；不审核专业擅长）。
 */
export const verifyStaff = (params: {
  page?: number;
  page_size?: number;
  work_type?: string;
  department?: string;
  status?: string;
  /** 仅返回信息不完整的人员（total 此时为缺失人数） */
  only_missing?: boolean;
}): Promise<StaffVerifyResponse> =>
  api.get('/data/verify-staff', { params }).then((r) => r.data);

// ==================== 备份 ====================

export const backupDatabase = () =>
  api.post('/data/backup').then((r) => r.data);

export const getBackupList = () =>
  api.get<{ filename: string; size: number; created_at: string; modified_at: string }[]>('/data/backups').then((r) => r.data);

export const restoreBackup = (filename: string) =>
  api.post('/data/restore', null, { params: { filename } }).then((r) => r.data);

export const uploadRestoreBackup = (file: File, confirmPassword?: string, onProgress?: (percent: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  if (confirmPassword) fd.append('confirm_password', confirmPassword);
  return uploadApi.post('/data/restore/upload', fd, {
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)); },
  }).then((r) => r.data);
};

export const downloadBackupFn = (filename: string) =>
  api.get('/data/download-backup', { params: { filename }, responseType: 'blob' }).then((r) => {
    downloadBlob(r.data, filename);
  });

export const deleteBackup = (filename: string) =>
  api.delete('/data/backups', { params: { filename } }).then((r) => r.data);

// ==================== 图片打包 ====================

/** 创建图片打包任务（后台异步，departmentId 必填，photoTypes 可选：'front'|'side'|'card' 多选，缺省全选） */
// [修复 2026-08-28] 新增 photoTypes 参数，支持按照片类型（正面照/侧面照/卡片照）单选或多选导出
export const createPackage = (departmentId: number, photoTypes?: string[]) => {
  // 使用 URLSearchParams 以重复 key 形式传递多值参数（photo_types=front&photo_types=side），
  // 兼容 FastAPI 的 Query(List[str]) 解析，避免 axios 默认数组序列化加 [] 后缀。
  const params = new URLSearchParams();
  params.append('department_id', String(departmentId));
  if (photoTypes && photoTypes.length) {
    photoTypes.forEach((t) => params.append('photo_types', t));
  }
  return api
    .post<{ id: number; status: string; message: string; photo_types?: string }>(
      '/data/export/packages',
      null,
      { params },
    )
    .then((r) => r.data);
};

/** 获取打包列表 */
export const getPackageList = () =>
  api.get<PackageItem[]>('/data/export/packages').then((r) => r.data);

/**
 * 下载打包文件
 *
 * [修复/问题12] 原实现用 `window.open(...?ftoken=...)` 把文件访问令牌放进 URL，
 * 令牌会被浏览器历史、服务器/代理访问日志、Referer 头记录，扩大泄露面。
 * 改为：用 fetch 携带 Authorization 头拉取二进制，再以 Blob 触发下载，
 * 令牌不再出现在 URL 中（后端亦已移除 ?token= 完整 JWT 鉴权，见问题19）。
 */
export const downloadPackage = async (packageId: number, filename: string) => {
  const res = await api.get(`/data/export/packages/${packageId}/download`, {
    responseType: 'blob',
  });
  // [修正 2026-09-22] 改用公共 downloadBlob（原实现写法本身正确，
  // 统一后全项目只有一处 Blob 下载实现，避免再出现"某一份漏了 appendChild"的情况）
  downloadBlob(res.data as Blob, filename || `package_${packageId}.zip`);
};

/** 删除打包记录及文件 */
export const deletePackage = (packageId: number) =>
  api.delete(`/data/export/packages/${packageId}`).then((r) => r.data);

export interface PackageItem {
  id: number;
  department_name: string;
  filename: string;
  file_size: number;
  status: 'packing' | 'completed' | 'expired' | 'failed';
  created_at: string;
  expires_at: string;
}

// ==================== 工具函数 ====================

// [修正 2026-09-22] 原先此处有一份本地 downloadBlob 实现（与 utils/fileUtils 的同名）。
// 全项目曾有三份写法互不相同的 Blob 下载代码，其中一份因缺少 appendChild 在
// Firefox 下完全无法下载（见 api/audit.ts 的历史问题）。现统一为从公共工具导入。
