// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

export interface RegulationCategory {
  id: number;
  name: string;
  code?: string;  // [新增] 类别代码（3位大写英文字母），旧数据可能为空
  sort_order: number;
  created_at?: string;
}

export interface RegulationHistory {
  id: number;
  regulation_id: number;
  version?: string;  // [新增] 版本号（如 V01_BSM_260807）
  content?: string;  // [新增] 该版本制度内容快照（列表页可能为空，详情用单独接口获取）
  edited_by?: string;
  edited_at?: string;
  change_summary?: string;
}

export interface Regulation {
  id: number;
  name: string;
  category_id?: number;
  category_name?: string;
  version?: string;
  content?: string;
  created_by?: string;
  updated_by?: string;
  created_at?: string;
  updated_at?: string;
  history?: RegulationHistory[];
}

export interface RegulationListResponse {
  items: Regulation[];
  total: number;
}
