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

/**
 * 触发浏览器下载一个 Blob。
 *
 * [新增 2026-09-22] 统一收敛全项目的"Blob 下载"写法。此前这段逻辑散落在多处
 * （api/data.ts 的 downloadBlob / downloadPackage、utils/fileUtils 的
 * downloadDesignFile、api/audit 的 exportSystemLogs），**且写法不一致** ——
 * 其中 exportSystemLogs 少了 `appendChild`，导致 <a> 未挂载到 DOM。
 *
 * ⚠️ 这一点并非风格问题：**未挂载到 document 的 <a>，在 Firefox 中 click()
 * 不会触发下载**（Chrome 通常无碍）。现象是"点了导出没反应"，且控制台无报错 ——
 * 很难往"少了一行 appendChild"上想。
 *
 * 另外，revoke 必须放在 click **之后**：过早释放会让下载尚未开始就失去数据源，
 * 大文件时尤为明显。
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  // 必须挂载到 DOM，否则 Firefox 下不会触发下载
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // 放在 click 之后释放：避免下载还没开始就失去数据源
  URL.revokeObjectURL(url);
}

/**
 * 把"可能是错误响应"的 Blob 转成可判断的结果。
 *
 * [新增 2026-09-22] axios 配置 `responseType: 'blob'` 时，**后端返回的错误 JSON
 * 同样会以 Blob 形式拿到** —— 于是"导出失败"的表现变成"下载了一个打不开的文件"，
 * 而界面上不显示任何错误，用户完全无从判断。
 *
 * 这里检测 Blob 是否为 JSON（错误响应），若是则解析出 detail 并抛出，
 * 让调用方能正常提示错误；否则返回 Blob 供下载。
 */
export async function ensureBlobIsFile(blob: Blob): Promise<Blob> {
  const type = (blob.type || '').toLowerCase();
  // 后端错误响应是 application/json；部分代理会返回 text/plain
  if (type.includes('application/json') || type.includes('text/plain')) {
    let detail = '';
    try {
      const text = await blob.text();
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed?.detail === 'string') detail = parsed.detail;
    } catch {
      // 不是 JSON（可能是真的二进制文件被误标了类型），交给调用方正常下载
      return blob;
    }
    if (detail) throw new Error(detail);
  }
  return blob;
}

/** 下载文件（以显示名作为保存名） */
export async function downloadDesignFile(fileId: number, name: string): Promise<void> {
  const response = await api.get(`/files/${fileId}/download`, { responseType: 'blob' });
  downloadBlob(await ensureBlobIsFile(response.data as Blob), name);
}

/** 扩展名 → 展示标签（无点的大写形式） */
export function fileExtLabel(ext?: string | null): string {
  return (ext || '').replace(/^\./, '').toUpperCase() || '文件';
}
