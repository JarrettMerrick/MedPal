// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 系统日志接口
 *
 * [调整 2026-09-11] 「信息修改」相关接口（待确认 / 已确认 / 确认 / 实体变更历史）
 * 已随该功能整体下线删除；信息修改提醒改由「站内信」承载（见 api/messages.ts）。
 */

import api from './client';

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

export const exportSystemLogs = (params: Omit<SystemLogParams, 'page' | 'page_size'>) =>
  api.get('/audit/system-logs/export', { params, responseType: 'blob' }).then((r) => {
    const url = window.URL.createObjectURL(new Blob([r.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = `系统日志_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    window.URL.revokeObjectURL(url);
  });

export const cleanupSystemLogs = (days: number = 90) =>
  api.delete<{ message: string; deleted: number }>('/audit/system-logs/cleanup', { params: { days } }).then((r) => r.data);
