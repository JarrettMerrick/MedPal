// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { LoginResponse, UserItem } from '../types/user';

export const login = (employee_id: string, password: string, remember_me: boolean = false) =>
  api.post<LoginResponse>('/auth/login', { employee_id, password, remember_me }).then((r) => r.data);

export const changePassword = (old_password: string, new_password: string) =>
  api.post('/auth/change-password', { old_password, new_password });

export const getMe = () => api.get('/auth/me').then((r) => r.data);

export const updateProfile = (data: {
  name?: string;
  department?: string;
  education?: string;
  title?: string;
  position?: string;
  expertise_short?: string;
  expertise_standard?: string;
  social_appointments?: string;
  honors?: string;
  remarks?: string;
}) =>
  api.put<UserItem>('/auth/profile', data).then((r) => r.data);

/**
 * [修复/问题3] refresh_token 已迁移到 HttpOnly Cookie，前端不再持有，
 * 因此 refresh_token 改为可选：不传时后端直接从 Cookie 读取并吊销。
 */
export const logout = (refresh_token?: string, access_token?: string) =>
  api.post('/auth/logout', { refresh_token, access_token });
