// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { Staff, StaffListResponse } from '../types/staff';

export const getStaffList = (params: {
  page?: number;
  page_size?: number;
  search?: string;
  department?: string;
  work_type?: string;
  status?: string;
}): Promise<StaffListResponse> =>
  api.get('/staff', { params }).then((r) => r.data);

/** 离职人员列表：[新增 2026-09-11] scope 支持 active 在档 / archived 已满保留期 / all 全部 */
export const getResignedStaff = (params: {
  page?: number;
  page_size?: number;
  search?: string;
  work_type?: string;
  scope?: 'active' | 'archived' | 'all';
}): Promise<StaffListResponse> =>
  api.get('/staff/resigned', { params }).then((r) => r.data);

export const getStaff = (employee_id: string): Promise<Staff> =>
  api.get(`/staff/${employee_id}`).then((r) => r.data);

export const createStaff = (data: Omit<Staff, 'status' | 'updated_by' | 'updated_at' | 'front_photo' | 'side_photo'>): Promise<Staff> =>
  api.post('/staff', data).then((r) => r.data);

export const updateStaff = (employee_id: string, data: Partial<Staff>): Promise<Staff> =>
  api.put(`/staff/${employee_id}`, data).then((r) => r.data);

export const deleteStaff = (employee_id: string): Promise<void> =>
  api.delete(`/staff/${employee_id}`).then((r) => r.data);

/**
 * 变更人员状态（在职/离职）
 * [调整 2026-09-11] 办理离职时可传 reason（离职原因），后端会记录离职时间与办理人
 */
export const updateStaffStatus = (
  employee_id: string,
  status: 'active' | 'resigned',
  reason?: string,
): Promise<{ message: string; status: string }> =>
  api.put(`/staff/${employee_id}/status`, null, { params: { status, ...(reason ? { reason } : {}) } }).then((r) => r.data);

export const getDepartmentCategory = (work_type: string): Promise<{ category: string }> =>
  api.get('/staff/department-category', { params: { work_type } }).then((r) => r.data);
