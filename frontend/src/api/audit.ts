// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 系统日志接口
 *
 * [调整 2026-09-11] 「信息修改」相关接口（待确认 / 已确认 / 确认 / 实体变更历史）
 * 已随该功能整体下线删除；信息修改提醒改由「站内信」承载（见 api/messages.ts）。
 */

import api from './client';
// [新增 2026-09-22] 统一的 Blob 下载与错误响应识别（修复导出失效问题，详见 exportSystemLogs 注释）
import { downloadBlob, ensureBlobIsFile } from '../utils/fileUtils';

export interface SystemLogItem {
  id: number;
  timestamp: string;
  level: string;
  level_label: string;
  category: string;
  category_label: string;
  operator: string | null;
  operator_name: string;
  content: string;
  ip_address: string;
  details: string | null;
}

export interface SystemLogParams {
  page?: number;
  page_size?: number;
  category?: string;
  level?: string;
  keyword?: string;
  start_date?: string;
  end_date?: string;
}

export const getSystemLogs = (params: SystemLogParams) =>
  api.get<{ items: SystemLogItem[]; total: number; page: number; page_size: number }>(
    '/audit/system-logs', { params }
  ).then((r) => r.data);

/**
 * 导出系统日志为 Excel。
 *
 * [修正 2026-09-22] 原实现有三个问题，都会表现为「日志无法导出」：
 *
 *   ① **`<a>` 未挂载到 DOM 就 click()** —— Firefox 下不会触发下载（Chrome 通常可以），
 *      现象是"点了导出没反应"，控制台也没有报错，极难定位。
 *      已改为使用公共工具 downloadBlob（内部会 appendChild）。
 *
 *   ② **`revokeObjectURL` 紧跟在 click 之后** —— 下载可能尚未开始就失去数据源，
 *      大文件时更易失败。公共工具已把释放放到 click 之后。
 *
 *   ③ **后端报错时会下载一个"打不开的假文件"** —— 因为 `responseType: 'blob'`
 *      会把错误 JSON 也当二进制收下，界面上看不到任何错误提示，用户只得到一个
 *      损坏的 xlsx。已用 ensureBlobIsFile 识别错误响应并抛出，让调用方能提示原因。
 *
 * 顺带修正文件名日期：原用 `toISOString()`（UTC），在北京时间凌晨会显示成前一天，
 * 与本项目"导出产物用北京时间"的口径不一致。改用本地日期。
 */
export const exportSystemLogs = async (
  params: Omit<SystemLogParams, 'page' | 'page_size'>,
): Promise<void> => {
  const r = await api.get('/audit/system-logs/export', { params, responseType: 'blob' });
  const blob = await ensureBlobIsFile(r.data as Blob);
  const now = new Date();
  const datePart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  downloadBlob(blob, `系统日志_${datePart}.xlsx`);
};

export const cleanupSystemLogs = (days: number = 90) =>
  api.delete<{ message: string; deleted: number }>('/audit/system-logs/cleanup', { params: { days } }).then((r) => r.data);
