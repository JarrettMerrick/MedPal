// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import client from './client';

export interface SystemConfig {
  id: number;
  config_key: string;
  config_value: string | null;
  description: string | null;
  updated_by: string | null;
  updated_at: string | null;
}

export async function getSystemConfig(key: string): Promise<SystemConfig> {
  const res = await client.get(`/system-config/${key}`);
  return res.data;
}

export async function updateSystemConfig(key: string, value: string): Promise<SystemConfig> {
  const res = await client.put(`/system-config/${key}`, { config_value: value });
  return res.data;
}