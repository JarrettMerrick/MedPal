// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 账号设置接口。
 *
 * - 读取走 `GET /api/account-settings`（需 system.config，敏感配置不下放给普通用户）；
 * - 保存复用现有 `PUT /api/system-config/{key}`（见 api/system-config.ts）。
 */
import client from './client';

export interface AccountSettings {
  /** 默认口令模板（可能为空，表示使用内置默认） */
  default_password_template: string;
  /** 实际生效的模板（空模板时为内置默认 MedPal@2026） */
  default_password_template_effective: string;
  /** 口令预览示例（{工号} 已替换为示例工号） */
  password_preview: string;
  /** 登录页注册开关 */
  registration_enabled: boolean;
}

/** 获取账号设置汇总（需 system.config） */
export async function getAccountSettings(): Promise<AccountSettings> {
  const res = await client.get('/account-settings');
  return res.data;
}
