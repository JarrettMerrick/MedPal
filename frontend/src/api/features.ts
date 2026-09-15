// [新增 2026-09-14] 功能开关（系统设置 → 功能开关）接口

import client from './client';

/** 功能标识（与后端 FEATURE_CONFIG_KEYS 的键一致） */
export type FeatureKey = 'messages' | 'signage' | 'regulation';

/** 各功能是否启用 */
export type FeatureFlags = Record<FeatureKey, boolean>;

/**
 * 读取功能开关（免登录公开接口）。
 *
 * 供前端在首屏（含登录页）即决定菜单与入口的显隐，
 * 避免"先渲染全部菜单、再闪一下消失"。
 */
export async function getFeatureFlags(): Promise<FeatureFlags> {
  const res = await client.get('/public/features');
  return res.data;
}

/** 设置页的功能项（含展示元信息，由后端 FEATURE_META 下发） */
export interface FeatureSettingItem {
  /** 功能标识：messages / signage / regulation */
  key: FeatureKey;
  /** 对应的系统配置 key，保存时提交给 PUT /api/system-config/{key} */
  config_key: string;
  label: string;
  /** 该开关影响的前端入口说明 */
  applies_to: string;
  description: string;
  enabled: boolean;
}

/** 功能开关设置页汇总（需 system.config 权限） */
export interface FeatureSettingsResult {
  /** 角色级门禁：所有功能开关**共用**的同一个权限点（合并后为 feature.access） */
  permission: string;
  features: FeatureSettingItem[];
}

export async function getFeatureSettings(): Promise<FeatureSettingsResult> {
  const res = await client.get('/feature-settings');
  return { permission: res.data.permission, features: res.data.features };
}
