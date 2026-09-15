// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 账号设置接口。
 *
 * - 读取走 `GET /api/account-settings`（需 system.config，敏感配置不下放给普通用户）；
 * - 保存复用现有 `PUT /api/system-config/{key}`（见 api/system-config.ts）。
 */
import client from './client';

/** [新增 2026-09-14] 科室维度的可重置账号数，用于「按科室定向重置」的范围选择 */
export interface DepartmentResetOption {
  /** 科室名称（与账号 users.department 的取值一一对应，故以名称而非 ID 作为筛选键） */
  name: string;
  /** 该科室下可被重置的账号数（不含超级管理员） */
  resettable_user_count: number;
}

export interface AccountSettings {
  /** 默认口令模板（可能为空，表示使用内置默认） */
  default_password_template: string;
  /** 实际生效的模板（空模板时为内置默认 MedPal@2026） */
  default_password_template_effective: string;
  /** 口令预览示例（{工号} 已替换为示例工号） */
  password_preview: string;
  /** 登录页注册开关 */
  registration_enabled: boolean;
  /** [新增 2026-09-14]「批量重置密码」不限科室（全员）时将覆盖的账号数（不含超级管理员） */
  resettable_user_count: number;
  /** [新增 2026-09-14] 会被跳过的超级管理员账号数 */
  super_admin_count: number;
  /** [新增 2026-09-14] 各科室可重置账号数（按科室管理顺序排序） */
  departments: DepartmentResetOption[];
  /** [新增 2026-09-14] 未分配科室的可重置账号数（仅在不限科室的全量重置中会被覆盖） */
  unassigned_user_count: number;
}

/**
 * [调整 2026-09-15] 批量重置密码任务（后台执行 + 进度轮询）。
 *
 * 后端改为异步任务模式：POST 只创建任务并**立即返回**，前端据此展示
 * 「实际进度」进度条（processed / total），并以 1s 间隔轮询本对象最新状态；
 * 完成 / 失败后在前端展示结果或错误。
 *
 * 注意 `uniform_password`：仅当口令模板不含 `{工号}` 时返回
 * （此时范围内账号得到同一个口令，回显便于管理员转告）；含占位符时为 null。
 */
export interface ResetTask {
  /** 任务 ID（轮询 / 恢复进度用） */
  task_id: number;
  /** running=进行中 / completed=已完成 / failed=失败 */
  status: 'running' | 'completed' | 'failed';
  /** 目标账号总数 */
  total: number;
  /** 已处理账号数（进度条按 processed / total 计算） */
  processed: number;
  /** 其中已停用账号数（仅供核对范围） */
  inactive_count: number;
  /** 被跳过的超级管理员账号数（已按本次科室范围统计） */
  super_admin_excluded: number;
  /** 因未分配科室而被跳过的账号数（仅定向重置时可能 > 0） */
  unassigned_excluded: number;
  /** 本次生效的科室范围；空数组表示不限科室（全员） */
  departments: string[];
  /** 是否为不限科室的全量重置 */
  is_all_departments: boolean;
  /** 本次生效的口令规则（模板） */
  password_rule: string;
  /** 是否范围内统一口令（模板不含 {工号}） */
  is_uniform: boolean;
  /** 统一口令时的明文口令，否则为 null */
  uniform_password: string | null;
  /** 操作者本人的账号是否也在重置范围内（是则需重新登录） */
  self_included: boolean;
  /** 完成后的结果文案（进行中为 null） */
  message: string | null;
  /** 失败原因摘要（仅 failed 时有值） */
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

/** 获取账号设置汇总（需 system.config） */
export async function getAccountSettings(): Promise<AccountSettings> {
  const res = await client.get('/account-settings');
  return res.data;
}

/**
 * [调整 2026-09-15] 批量重置密码（除超级管理员外），支持按科室单选/多选定向。
 *
 * **异步任务模式**：本调用只创建任务并**立即返回**（毫秒级），前端应随后按
 * `task_id` 轮询 `getResetTask` 展示进度条——这既符合"按实际进度展示"，
 * 也避免用户在长等待中重复点击。若已有进行中的任务，后端返回 409，
 * 前端应改为展示「进行中任务」的进度（见 getLatestResetTask）。
 *
 * 需同时具备 system.config 与 user.reset_password 权限；
 * `password` 为操作者本人的当前登录密码（后端二次确认，错误则 400 且不做任何改动）。
 *
 * @param departments 限定重置的科室名称列表：
 *   传 1 个 = 单科室定向，传多个 = 多科室批量；
 *   传空数组 / 省略 = 不限科室（即「除超级管理员外全员」语义）。
 *   名称须为系统已知科室，否则后端返回 400（防止前端缓存了已删除科室造成静默漏改）。
 *
 * 新口令按「默认密码规则（模板）」生成，重置后范围内账号需重新登录并强制改密。
 */
export async function resetAllPasswords(
  password: string,
  departments: string[] = [],
): Promise<ResetTask> {
  const res = await client.post('/account-settings/reset-all-passwords', {
    password,
    departments,
  });
  return res.data;
}

/** 查询指定重置任务的进度（前端 1s 轮询；后端为单表查询，毫秒级返回） */
export async function getResetTask(taskId: number): Promise<ResetTask> {
  const res = await client.get(`/account-settings/reset-all-passwords/status/${taskId}`);
  return res.data.task;
}

/**
 * 最近的批量重置任务（无任务时为 null）。
 *
 * 供页面加载时恢复进度：刷新页面 / 重新进入后若最近任务仍在运行，
 * 直接切回进度条展示，避免用户以为"没反应"而重复提交。
 */
export async function getLatestResetTask(): Promise<ResetTask | null> {
  const res = await client.get('/account-settings/reset-all-passwords/status');
  return res.data.task ?? null;
}
