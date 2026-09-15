// [新增 2026-09-15] 通知设置（系统设置 → 通知设置）接口
//
// 与 `notifications.ts`（站内信收件箱）区分：本文件面向**通知中心的管理配置**，
// 对应后端 `/api/notification-settings` 系列接口：
//   GET    /notification-settings                 设置页汇总（事件清单 + 生效配置 + 默认值）
//   GET    /notification-settings/options         自定义收件人的可选角色 / 科室 / 权限
//   PUT    /notification-settings/{code}          保存某事件的开关 / 文案 / 收件人规则
//   POST   /notification-settings/{code}/reset    恢复某事件的默认配置
//   POST   /notification-settings/{code}/preview  干跑预览（不发送）
//   POST   /notification-settings/{code}/test     向本人发送一封测试站内信

import client from './client';

/** 单条收件人规则（type 取值见后端 RECIPIENT_RULE_TYPES） */
export interface RecipientRuleItem {
  type: string;
  /** 需要取值的规则（permissions / roles / departments / users）的取值列表 */
  value?: string[] | null;
  /** 仅 dept_managers / permissions 支持 "event_department"（限本事件相关科室） */
  scope?: string | null;
}

/** 自定义收件人规则集合 */
export interface RecipientRules {
  include: RecipientRuleItem[];
  /** 是否排除操作者本人（默认 true） */
  exclude_actor: boolean;
}

/** 事件可用变量（模板中可用的 {变量} 及其说明） */
export interface NotificationVariable {
  name: string;
  desc: string;
}

/** 一个可配置的通知事件（生效配置 + 注册表默认值） */
export interface NotificationEventItem {
  /** 事件编码（保存 / 预览 / 测试以此为路径参数） */
  code: string;
  /** 设置页分组（人员管理 / 科室管理 / 工卡管理 / 系统运维 ...） */
  module: string;
  label: string;
  description: string;
  /** 注册表默认是否发送（未配置时的行为） */
  default_enabled: boolean;
  /** 当前生效的开关 */
  enabled: boolean;
  /** 该事件是否存在规则覆盖行 */
  customized: boolean;
  is_custom_title: boolean;
  is_custom_content: boolean;
  is_custom_recipients: boolean;
  /** 默认收件人范围的人话说明 */
  default_recipient_hint: string;
  default_title: string;
  default_content: string;
  /** 生效标题模板（自定义优先，否则为默认） */
  title_template: string;
  content_template: string;
  /** default（业务内置默认）/ custom（自定义规则） */
  recipient_mode: string;
  recipient_rules: RecipientRules | null;
  variables: NotificationVariable[];
  /** 预览用示例变量值 */
  sample: Record<string, string>;
  updated_by: string | null;
  updated_at: string | null;
}

/** 收件人规则类型（由后端下发，前端据此渲染编辑器） */
export interface RecipientRuleType {
  type: string;
  label: string;
  /** 是否需要选择具体取值 */
  needs_value: boolean;
  /** 取值来源（permissions / roles / departments / users） */
  value_kind?: string;
  /** 是否支持「限本事件相关科室」范围 */
  scope: boolean;
}

/** 通知设置页汇总（需 feature.notification 权限） */
export interface NotificationSettingsResult {
  events: NotificationEventItem[];
  /** 模块分组展示顺序 */
  modules: string[];
  rule_types: RecipientRuleType[];
  limits: { title: number; content: number };
  /** 角色级门禁：通知设置权限点（feature.notification，角色管理「系统设置」分类） */
  permission: string;
}

/** 自定义收件人的候选项 */
export interface RecipientOptions {
  roles: Array<{ value: string; label: string }>;
  departments: Array<{ value: string; label: string }>;
  permissions: Array<{ value: string; label: string; category: string | null }>;
}

/** 保存某事件的规则覆盖（文案传空字符串 = 恢复默认模板） */
export interface NotificationRulePayload {
  enabled: boolean;
  title_template?: string | null;
  content_template?: string | null;
  recipient_mode: string;
  recipient_rules?: RecipientRules | null;
}

/** 预览请求（传草稿值，不落库不发送） */
export interface NotificationPreviewPayload {
  title_template?: string | null;
  content_template?: string | null;
  recipient_mode?: string | null;
  recipient_rules?: RecipientRules | null;
  /** 事件相关科室（自定义规则 scope=event_department 时用于数据范围过滤） */
  department?: string | null;
}

/** 预览结果 */
export interface NotificationPreviewResult {
  title: string;
  content: string;
  mode?: string;
  recipients: {
    total: number;
    preview: Array<{ employee_id: string; name: string; department: string | null }>;
  };
  /** 收件人规则解析失败时的错误说明（文案仍会返回） */
  error?: string;
}

export async function getNotificationSettings(): Promise<NotificationSettingsResult> {
  const res = await client.get('/notification-settings');
  return res.data;
}

export async function getRecipientOptions(): Promise<RecipientOptions> {
  const res = await client.get('/notification-settings/options');
  return res.data;
}

export async function saveNotificationRule(
  code: string,
  payload: NotificationRulePayload,
): Promise<{ ok: boolean; event_code: string; enabled: boolean; customized: boolean }> {
  const res = await client.put(`/notification-settings/${code}`, payload);
  return res.data;
}

export async function resetNotificationRule(
  code: string,
): Promise<{ ok: boolean; event_code: string; removed: boolean }> {
  const res = await client.post(`/notification-settings/${code}/reset`);
  return res.data;
}

export async function previewNotificationRule(
  code: string,
  payload: NotificationPreviewPayload,
): Promise<NotificationPreviewResult> {
  const res = await client.post(`/notification-settings/${code}/preview`, payload);
  return res.data;
}

export async function sendTestNotification(
  code: string,
): Promise<{ ok: boolean; title: string; content: string }> {
  const res = await client.post(`/notification-settings/${code}/test`);
  return res.data;
}
