// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { StaffCardListResponse, StaffCard } from '../types/staff-card';

export const getCards = (params: {
  entity_type?: string;
  entity_id?: string;
  status?: string;
  page?: number;
  page_size?: number;
}) => api.get<StaffCardListResponse>('/cards', { params }).then((r) => r.data);

export const getCard = (cardId: number) =>
  api.get(`/cards/${cardId}`).then((r) => r.data);

// [修复 2026-09-03] 移除手动设置的 Content-Type，让 axios 自动设置带 boundary 的 multipart/form-data
export const uploadCard = (file: File, entityType: string, entityId: string) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post(`/cards?entity_type=${entityType}&entity_id=${entityId}`, formData).then((r) => r.data);
};

export const confirmCard = (cardId: number) =>
  api.put(`/cards/${cardId}/confirm`).then((r) => r.data);

export const rejectCard = (cardId: number, reason?: string) =>
  api.put(`/cards/${cardId}/reject`, { reject_reason: reason }).then((r) => r.data);

export const deleteCard = (cardId: number) =>
  api.delete(`/cards/${cardId}`);
