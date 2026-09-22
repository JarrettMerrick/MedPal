// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { RegulationCategory, Regulation, RegulationHistory, RegulationListResponse } from '../types/regulation';

// ==================== 类别管理 ====================

export const getCategories = () =>
  api.get<RegulationCategory[]>('/regulations/categories').then(r => r.data);

export const createCategory = (name: string, code: string) =>
  api.post<RegulationCategory>('/regulations/categories', { name, code }).then(r => r.data);

export const updateCategory = (id: number, data: { name?: string; code?: string }) =>
  api.put<RegulationCategory>(`/regulations/categories/${id}`, data).then(r => r.data);

export const deleteCategory = (id: number) =>
  api.delete(`/regulations/categories/${id}`).then(r => r.data);

// ==================== 制度管理 ====================

export const getRegulations = (params: { keyword?: string; category_id?: number; page?: number; page_size?: number }) =>
  api.get<RegulationListResponse>('/regulations', { params }).then(r => r.data);

export const getRegulation = (id: number) =>
  api.get<Regulation>(`/regulations/${id}`).then(r => r.data);

export const createRegulation = (data: Partial<Regulation>) =>
  api.post<Regulation>('/regulations', data).then(r => r.data);

export const updateRegulation = (id: number, data: Partial<Regulation>) =>
  api.put<Regulation>(`/regulations/${id}`, data).then(r => r.data);

export const deleteRegulation = (id: number) =>
  api.delete(`/regulations/${id}`).then(r => r.data);

// ==================== 历史版本管理 ====================

export const getRegulationHistory = (id: number) =>
  api.get<RegulationHistory[]>(`/regulations/${id}/history`).then(r => r.data);

export const getRegulationHistoryDetail = (regulationId: number, historyId: number) =>
  api.get<RegulationHistory>(`/regulations/${regulationId}/history/${historyId}`).then(r => r.data);
