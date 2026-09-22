// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 楼层号（floor_number）统一规范 —— 前端唯一来源。
 *
 * [新增 2026-09-17] 楼层号由纯数字改为「字母前缀 + 数字」，支持字母编号：
 *   - 地上：F + 层数     F1 = 一层、F3 = 三层、F10 = 十层
 *   - 地下：B + 深度     B1 = 地下一层、B2 = 地下二层
 * 例如「地下一层」输入 B1，「地上五层」输入 F5。
 *
 * 配套三类工具，全站统一口径（后端 app/schemas/campus.py 实现同一规则）：
 *   1) normalizeFloorNumber —— 输入规范化（f3、F03、3、-1 均可识别）
 *   2) floorLabel          —— 展示标签（F3-门诊层）
 *   3) floorSortValue      —— 排序值（B 系列在前、越深越靠前）
 */

/** 楼层号合法格式：F1~F999（地上）/ B1~B999（地下） */
export const FLOOR_NUMBER_PATTERN = /^[BF][1-9]\d{0,2}$/;

/** 楼层号格式说明（表单提示文案复用） */
export const FLOOR_NUMBER_HINT =
  '地上用 F+层数（如 F3＝三层），地下用 B+深度（如 B1＝地下一层）';

/**
 * 输入规范化：把用户可能的多种写法统一成标准楼层号。
 *   f3 / F03 / 3   → F3    （地上三层）
 *   b1 / -1 / B01  → B1    （地下一层）
 * @returns 标准楼层号；返回 null 表示无法识别（由调用方给出格式错误提示）
 */
export function normalizeFloorNumber(raw?: string | number | null): string | null {
  if (raw === null || raw === undefined) return null;
  const s = String(raw).trim().toUpperCase().replace(/\s+/g, '');
  if (!s) return null;

  // 纯数字 / 负数：兼容旧习惯输入（3 → F3；-1 → B1；0 层不合法）
  if (/^-?\d+$/.test(s)) {
    const n = Number(s);
    if (n === 0) return null;
    if (Math.abs(n) > 999) return null;
    return `${n < 0 ? 'B' : 'F'}${Math.abs(n)}`;
  }

  // 已带前缀：去掉多余前导零（F03 → F3）
  const m = /^([BF])0*(\d+)$/.exec(s);
  if (m) {
    const n = Number(m[2]);
    if (n <= 0 || n > 999) return null;
    return `${m[1]}${n}`;
  }
  return null;
}

/**
 * 楼层排序值：B3(-3) < B2(-2) < B1(-1) < F1(1) < F2(2)。
 * 地下层在前、越深越靠前；无法识别的值返回 0（排在最上层之前）。
 */
export function floorSortValue(floorNumber?: string | null): number {
  const m = /^([BF])(\d+)$/.exec((floorNumber || '').trim().toUpperCase());
  if (!m) return 0;
  const n = Number(m[2]);
  return m[1] === 'B' ? -n : n;
}

/** 楼层比较器（升序），用于前端排序 */
export function compareFloorNumber(
  a?: string | null,
  b?: string | null,
): number {
  return floorSortValue(a) - floorSortValue(b);
}

/**
 * 楼层展示标签：有楼层名称时拼接编号，保证楼层号始终可见。
 *   { floor_number: 'F3', floor_name: '门诊层' } → 'F3-门诊层'
 *   { floor_number: 'B1' }                      → 'B1'
 */
export function floorLabel(
  floor?: { floor_number?: string | null; floor_name?: string | null } | null,
): string {
  if (!floor) return '';
  const num = (floor.floor_number || '').trim();
  const name = (floor.floor_name || '').trim();
  if (num && name) return `${num}-${name}`;
  return num || name;
}
