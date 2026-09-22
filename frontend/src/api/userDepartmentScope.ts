// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';

export interface UserDepartmentScopeItem {
  id: number;
  employee_id: string;
  department_id: number;
  department_name: string;
  created_at: string;
}

export interface UserDepartmentScopeListResponse {
  items: UserDepartmentScopeItem[];
  total: number;
}

// 获取用户科室权限范围
export const getUserDepartmentScope = (employeeId: string) =>
  api.get<UserDepartmentScopeListResponse>(`/user-department-scope/${employeeId}`).then((r) => r.data);

// 添加用户科室关联
export const addUserDepartmentScope = (employeeId: string, departmentId: number) =>
  api.post<UserDepartmentScopeItem>(`/user-department-scope/${employeeId}`, { department_id: departmentId }).then((r) => r.data);

// 删除用户科室关联
export const deleteUserDepartmentScope = (employeeId: string, scopeId: number) =>
  api.delete(`/user-department-scope/${employeeId}/${scopeId}`).then((r) => r.data);

// 批量更新用户科室权限范围
export const updateUserDepartmentScope = (employeeId: string, departmentIds: number[]) =>
  api.put<UserDepartmentScopeListResponse>(`/user-department-scope/${employeeId}`, { department_ids: departmentIds }).then((r) => r.data);

// 获取当前用户可管理的科室列表
export const getManagedDepartments = () =>
  api.get<string[]>('/user-department-scope/managed-by-me').then((r) => r.data);