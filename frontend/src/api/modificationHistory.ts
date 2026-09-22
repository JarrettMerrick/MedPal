// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 修改历史查询接口。
 *
 * [新增 2026-09-15] 人员详情页 / 科室详情页的「修改历史」按钮使用：
 * 展示所修改的字段及修改前 / 修改后对比，只取最近三次修改。
 *
 * 数据源为后端 modification_history 表（人员编辑、科室编辑、状态变更等
 * 都会写入），后端已按详情页同款权限与数据范围做了访问校验。
 */
import client from './client';

/** 单个字段的前后对比 */
export interface ModificationFieldDiff {
  /** 字段中文名，如「姓名」「科室」 */
  label: string;
  /** 修改前（空字符串表示原值为空） */
  before: string;
  /** 修改后（空字符串表示新值为空） */
  after: string;
}

/** 一条修改记录 */
export interface ModificationHistoryItem {
  id: number;
  /** 修改时间（UTC ISO 字符串，展示时用 utils/time.ts 转本地时区） */
  modified_at: string | null;
  /** 操作人工号 */
  modified_by: string | null;
  /** 操作人姓名（查不到时回落为工号） */
  modified_by_name: string | null;
  /** 字段级前后对比（表格展示） */
  fields: ModificationFieldDiff[];
  /** 无法拆成前后值的说明性文字（如「新增人员: ...」「特色技术(新增1/删除0/修改2)」） */
  notes: string[];
  /** 原始摘要文本（兜底展示） */
  summary: string;
}

export interface ModificationHistoryResult {
  items: ModificationHistoryItem[];
  /** 该实体累计修改次数，用于提示「共 N 次，仅显示最近 3 次」 */
  total: number;
  /** 本次返回的条数上限 */
  limit: number;
}

/** 详情页固定展示的条数（需求：只保留最近三次修改） */
export const MODIFICATION_HISTORY_LIMIT = 3;

/**
 * 查询某实体的最近修改记录。
 * @param entityType staff=人员 / department=科室
 * @param entityId   人员为工号，科室为科室 ID
 */
export async function getModificationHistory(
  entityType: 'staff' | 'department',
  entityId: string | number,
  limit: number = MODIFICATION_HISTORY_LIMIT,
): Promise<ModificationHistoryResult> {
  const res = await client.get(`/audit/history/${entityType}/${entityId}`, {
    params: { limit },
  });
  return res.data;
}
