// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';

export interface NotificationItem {
  id: number;
  title: string;
  content: string | null;
  related_type: string | null;
  related_id: number | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  total: number;
  page: number;
  page_size: number;
}

export const getNotifications = (params: { page?: number; page_size?: number }) =>
  api.get<NotificationListResponse>('/notifications', { params }).then((r) => r.data);

export const getUnreadCount = () =>
  api.get<{ count: number }>('/notifications/unread-count').then((r) => r.data);

export const markNotificationRead = (id: number) =>
  api.put(`/notifications/${id}/read`).then((r) => r.data);

export const markAllNotificationsRead = () =>
  api.put('/notifications/read-all').then((r) => r.data);
