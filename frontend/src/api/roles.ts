// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { RoleListResponse, PermissionCategory, RoleOption } from '../types/role';

export const getRoles = (params: { page?: number; page_size?: number; search?: string }) =>
  api.get<RoleListResponse>('/roles', { params }).then((r) => r.data);

export const getAllRoles = () =>
  api.get<RoleOption[]>('/roles/all').then((r) => r.data);

export const getRole = (id: number) =>
  api.get<import('../types/role').Role>(`/roles/${id}`).then((r) => r.data);

export const getPermissionsByCategory = () =>
  api.get<PermissionCategory[]>('/roles/permissions').then((r) => r.data);

export const createRole = (data: { name: string; display_name: string; description?: string; department_scope?: string; work_type_scope?: string; permission_ids: number[] }) =>
  api.post('/roles', data).then((r) => r.data);

export const updateRole = (id: number, data: { display_name?: string; description?: string; department_scope?: string; work_type_scope?: string; permission_ids?: number[] }) =>
  api.put(`/roles/${id}`, data).then((r) => r.data);

export const deleteRole = (id: number) =>
  api.delete(`/roles/${id}`).then((r) => r.data);
