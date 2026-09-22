// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 文件库通用工具：文件大小格式化、带鉴权的预览与下载。
 *
 * [新增 2026-09-17] 文件库的预览/下载走**后端鉴权接口**（/api/files/{id}/preview|download），
 * 不使用 /uploads 静态直链 —— 浏览器原生 <img>/<iframe> 无法携带 Authorization 头，
 * 因此统一以 blob 方式取回再转 objectURL，确保请求始终带令牌。
 */
import api from '../api/client';

/** 文件大小格式化：1536 → 1.5 KB */
export function formatFileSize(size?: number | null): string {
  if (size === null || size === undefined || Number.isNaN(size)) return '-';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/** 取回文件预览的 objectURL（调用方负责在合适时机 revokeObjectURL） */
export async function fetchPreviewObjectUrl(fileId: number): Promise<string> {
  const response = await api.get(`/files/${fileId}/preview`, { responseType: 'blob' });
  return URL.createObjectURL(response.data as Blob);
}

/** 下载文件（以显示名作为保存名） */
export async function downloadDesignFile(fileId: number, name: string): Promise<void> {
  const response = await api.get(`/files/${fileId}/download`, { responseType: 'blob' });
  const url = URL.createObjectURL(response.data as Blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** 扩展名 → 展示标签（无点的大写形式） */
export function fileExtLabel(ext?: string | null): string {
  return (ext || '').replace(/^\./, '').toUpperCase() || '文件';
}
