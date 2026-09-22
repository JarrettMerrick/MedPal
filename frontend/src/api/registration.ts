// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/** 注册与审核接口。 */
import client from './client';

export interface WorkTypeOption {
  value: string;
  label: string;
}

export interface RegistrationOptions {
  enabled: boolean;
  work_types: WorkTypeOption[];
  departments: string[];
}

export interface RegistrationPayload {
  employee_id: string;
  name: string;
  password: string;
  work_type: string;
  department: string;
}

export interface RegistrationSubmitResult {
  status: string;
  id: number;
  /**
   * [新增 2026-09-17] 注册成功即可凭工号密码登录（审核通过前仅有个人信息相关权限）。
   * 保留字段以便前端在成功页提示「可直接登录」。
   */
  can_login?: boolean;
  /** 若该工号上次申请被驳回，回显驳回原因 */
  last_reject_reason: string | null;
}

export type RegistrationStatus = 'pending' | 'approved' | 'rejected';

export interface RegistrationRequestItem {
  id: number;
  employee_id: string;
  name: string;
  work_type: string;
  department: string;
  status: RegistrationStatus;
  reject_reason: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
}

/** 登录页注册入口所需的公开选项（免登录） */
export async function getRegistrationOptions(): Promise<RegistrationOptions> {
  const res = await client.get('/public/registration/options');
  return res.data;
}

/** 提交注册申请（免登录） */
export async function submitRegistration(payload: RegistrationPayload): Promise<RegistrationSubmitResult> {
  const res = await client.post('/public/registration', payload);
  return res.data;
}

/** 注册申请列表（需 user.approve） */
export async function listRegistrationRequests(params: {
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<{ total: number; page: number; page_size: number; items: RegistrationRequestItem[] }> {
  const res = await client.get('/registration-requests', { params });
  return res.data;
}

/** 审核通过（需 user.approve） */
export async function approveRegistration(id: number): Promise<{ message: string; employee_id: string }> {
  const res = await client.post(`/registration-requests/${id}/approve`);
  return res.data;
}

/** 驳回申请（需 user.approve） */
export async function rejectRegistration(id: number, reason: string): Promise<{ message: string }> {
  const res = await client.post(`/registration-requests/${id}/reject`, { reason });
  return res.data;
}

/** 待审数量（需 user.approve） */
export async function getRegistrationPendingCount(): Promise<number> {
  const res = await client.get('/registration-requests/pending-count');
  return res.data?.count ?? 0;
}
