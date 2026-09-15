// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 品牌（单位信息）接口。
 *
 * - 读取走**公开**接口 `/api/public/branding`（免登录），登录页也能展示单位 Logo/名称；
 * - Logo 上传/重置需 `system.config` 权限；
 * - 单位名称的保存复用现有 `PUT /api/system-config/{key}`（见 api/system-config.ts）。
 */
import client, { uploadApi } from './client';

export interface BrandingInfo {
  org_name_cn: string;
  org_name_en: string;
  /** 系统名称（后端固定返回 settings.app_name） */
  system_name: string;
  /** Logo 公开访问路径，未配置为空字符串 */
  logo_url: string;
  /** 宣传标语，未配置或已被管理员清空时为空字符串（展示方据此隐藏） */
  slogan: string;
  updated_at: string | null;
}

/** 获取公开品牌信息（免登录） */
export async function getBranding(): Promise<BrandingInfo> {
  const res = await client.get('/public/branding');
  return res.data;
}

/** 上传/更换单位 Logo（multipart，需 system.config 权限） */
export async function uploadBrandLogo(
  file: File,
): Promise<{ logo_url: string; updated_at: string | null }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await uploadApi.post('/branding/logo', formData);
  return res.data;
}

/** 重置单位 Logo 为内置默认图（需 system.config 权限） */
export async function resetBrandLogo(): Promise<{ logo_url: string; updated_at: string | null }> {
  const res = await client.delete('/branding/logo');
  return res.data;
}
