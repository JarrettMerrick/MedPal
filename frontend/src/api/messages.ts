// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 站内信接口（统一消息中心）
 *
 * [新增 2026-09-11] 系统通知 + 人工群发/私发统一走本模块，
 * 顶栏铃铛与「站内信」页面共用同一套后端接口。
 */

import api from './client';

export type MessageType = 'system' | 'broadcast' | 'direct';
/** 收件箱筛选：全部（不含归档）/ 未读 / 星标 / 归档 */
export type InboxBox = 'all' | 'unread' | 'starred' | 'archived';
/** 群发目标类型 */
export type BroadcastTarget = 'all' | 'departments' | 'roles' | 'permissions' | 'users';

export interface MessageItem {
  id: number;
  title: string;
  content: string | null;
  msg_type: MessageType;
  sender_id: string | null;
  sender_name: string | null;
  related_type: string | null;
  related_id: number | null;
  created_at: string;
  is_read: boolean;
  is_starred: boolean;
  is_archived: boolean;
  tag_id: number | null;
  tag_name: string | null;
  tag_color: string | null;
}

export interface InboxResponse {
  items: MessageItem[];
  total: number;
  page: number;
  page_size: number;
  unread: number;
}

export interface SentItem {
  id: number;
  title: string;
  content: string | null;
  msg_type: MessageType;
  created_at: string;
  recipient_count: number;
  read_count: number;
}

export interface SentResponse {
  items: SentItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface SentRecipient {
  employee_id: string;
  name: string | null;
  department: string | null;
  is_read: boolean;
  read_at: string | null;
}

export interface SentDetail extends SentItem {
  recipients: SentRecipient[];
}

export interface MessageTagItem {
  id: number;
  name: string;
  color: string | null;
  sort_order: number;
  count: number;
}

export interface RecipientPreview {
  total: number;
  preview: { employee_id: string; name: string | null; department: string | null }[];
}

export interface SendMessagePayload {
  title: string;
  content: string;
  send_type: 'direct' | 'broadcast';
  recipients?: string[];
  target_type?: BroadcastTarget;
  target_values?: string[];
}

// ---------- 收件箱 / 发件箱 ----------

export const listInbox = (params: {
  page?: number;
  page_size?: number;
  box?: InboxBox;
  tag_id?: number;
  keyword?: string;
  msg_type?: MessageType;
}) => api.get<InboxResponse>('/messages', { params }).then((r) => r.data);

export const getUnreadCount = () =>
  api.get<{ count: number }>('/messages/unread-count').then((r) => r.data);

export const listSent = (params: { page?: number; page_size?: number; keyword?: string }) =>
  api.get<SentResponse>('/messages/sent', { params }).then((r) => r.data);

export const getSentDetail = (id: number) =>
  api.get<SentDetail>(`/messages/sent/${id}`).then((r) => r.data);

export const getMessageDetail = (id: number) =>
  api.get<MessageItem>(`/messages/${id}`).then((r) => r.data);

// ---------- 状态与标注 ----------

export const markRead = (id: number) => api.put(`/messages/${id}/read`).then((r) => r.data);

export const markReadBatch = (ids: number[], isRead = true) =>
  api.put('/messages/mark-read', { ids, is_read: isRead }).then((r) => r.data);

export const markAllRead = () => api.put('/messages/read-all').then((r) => r.data);

/** 标注：星标 / 归档 / 自定义标签（字段不传=不修改；clearTag=true 时清除标签） */
export const updateFlags = (payload: {
  ids: number[];
  is_starred?: boolean;
  is_archived?: boolean;
  tag_id?: number;
  clear_tag?: boolean;
}) => api.put('/messages/flags', payload).then((r) => r.data);

export const bulkDelete = (ids: number[]) =>
  api.post('/messages/bulk-delete', { ids }).then((r) => r.data);

export const deleteMessage = (id: number) =>
  api.delete(`/messages/${id}`).then((r) => r.data);

// ---------- 标签字典 ----------

export const listTags = () =>
  api.get<MessageTagItem[]>('/messages/tags').then((r) => r.data);

export const createTag = (name: string, color?: string) =>
  api.post<MessageTagItem>('/messages/tags', { name, color }).then((r) => r.data);

export const updateTag = (id: number, data: { name?: string; color?: string }) =>
  api.put(`/messages/tags/${id}`, data).then((r) => r.data);

export const deleteTag = (id: number) => api.delete(`/messages/tags/${id}`).then((r) => r.data);

// ---------- 发送 ----------

export const previewRecipients = (target_type: BroadcastTarget, target_values: string[]) =>
  api
    .post<RecipientPreview>('/messages/recipients/preview', { target_type, target_values })
    .then((r) => r.data);

export const sendMessage = (payload: SendMessagePayload) =>
  api.post<{ message: string; id: number | null; recipient_count: number }>('/messages', payload).then((r) => r.data);
