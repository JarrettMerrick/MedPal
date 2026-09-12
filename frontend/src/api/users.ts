// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { UserListResponse } from '../types/user';

export const getUsers = (params: { page?: number; page_size?: number; search?: string; role?: string; has_profile?: string }) =>
  api.get<UserListResponse>('/users', { params }).then((r) => r.data);

export const createUser = (data: Record<string, unknown>) =>
  api.post('/users', data).then((r) => r.data);

export const updateUser = (employee_id: string, data: Record<string, unknown>) =>
  api.put(`/users/${employee_id}`, data).then((r) => r.data);

export interface ResetPasswordResult {
  message: string;
  /** 服务端随机生成的明文新密码，管理员需转告使用者 */
  password: string;
}

export const resetPassword = (employee_id: string) =>
  api.post<ResetPasswordResult>(`/users/${employee_id}/reset-password`).then((r) => r.data);

export const deleteUser = (employee_id: string) =>
  api.delete(`/users/${employee_id}`).then((r) => r.data);

export const batchCreateFromStaff = () =>
  api.post<{ created: number; skipped: number; message: string }>('/users/batch-create-from-staff').then((r) => r.data);
