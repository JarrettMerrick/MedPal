// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 人员信息变更审核接口。
 *
 * [新增 2026-09-11] 人员信息「立即生效 + 追认审核」：
 * 提交即生效（页面立刻显示最新值），同时生成待审任务；
 * 审核通过 = 追认，审核驳回 = 回滚到提交前旧值。
 */
import client from './client';

export type StaffChangeStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

export interface StaffChangeItem {
  id: number;
  employee_id: string;
  staff_name: string | null;
  department: string | null;
  change_summary: string | null;
  changed_fields: string[];
  changed_labels: string[];
  review_level: 'none' | 'dept' | 'admin';
  /** 审核人范围文案：科室负责人 / 超级管理员 / 免审 */
  level_label: string;
  status: StaffChangeStatus;
  /** 变更来源：self 个人中心 / admin 人员编辑 / photo 照片上传 */
  source: 'self' | 'admin' | 'photo';
  submitted_by: string;
  submitted_by_name: string | null;
  submitted_at: string | null;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  reject_reason: string | null;
  review_note: string | null;
  /** 驳回/撤回时是否已回滚 */
  rolled_back: boolean;
  /** 回滚说明（冲突未回滚时提示人工核对） */
  rollback_note: string | null;
  conflict_fields: string[];
  reminded_at: string | null;
  escalated_at: string | null;
  /** 当前登录人是否有权审核该条 */
  can_review: boolean;
}

export interface StaffChangeListResult {
  total: number;
  page: number;
  page_size: number;
  items: StaffChangeItem[];
}

/** 待我审核的变更（需 staff.approve） */
export async function listStaffChanges(params: {
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<StaffChangeListResult> {
  const res = await client.get('/staff-changes', { params });
  return res.data;
}

/** 待审数量（菜单角标，需 staff.approve） */
export async function getStaffChangePendingCount(): Promise<number> {
  const res = await client.get('/staff-changes/pending-count');
  return res.data?.count ?? 0;
}

/** 我提交的变更（个人中心「我的提交」） */
export async function listMyStaffChanges(params: {
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<StaffChangeListResult> {
  const res = await client.get('/staff-changes/mine', { params });
  return res.data;
}

/** 审核通过（追认） */
export async function approveStaffChange(id: number): Promise<{
  message: string;
  applied_deferred: string[];
  conflict_fields: string[];
}> {
  const res = await client.post(`/staff-changes/${id}/approve`);
  return res.data;
}

/** 驳回（回滚到提交前旧值） */
export async function rejectStaffChange(id: number, reason: string): Promise<{
  message: string;
  rolled_back: string[];
  conflict_fields: string[];
}> {
  const res = await client.post(`/staff-changes/${id}/reject`, { reason });
  return res.data;
}

/** 撤回自己提交的待审变更 */
export async function cancelStaffChange(id: number): Promise<{ message: string; rolled_back: string[] }> {
  const res = await client.post(`/staff-changes/${id}/cancel`);
  return res.data;
}

/** 某人员的待审变更（详情页/列表页提示用） */
export async function listStaffChangesByStaff(employeeId: string): Promise<{
  total: number;
  items: StaffChangeItem[];
}> {
  const res = await client.get(`/staff-changes/by-staff/${employeeId}`);
  return res.data;
}
