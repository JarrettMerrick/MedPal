// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 时间显示工具（全项目**唯一**的时间解析/格式化入口）
 * ================================================================
 * 统一约定：
 *   1. 后端一律以 UTC 存储，接口输出统一为带 "Z" 的 ISO-8601 UTC
 *      （如 2026-09-16T07:27:03Z，见后端 utils.to_iso_utc）；
 *   2. 前端一律经本模块转换后显示。**禁止** `new Date(x).toLocaleString()`、
 *      `dayjs(x).format()` 或把时间字符串直接拼进 JSX —— 无时区标记的 ISO 串会被
 *      浏览器按**本地时区**解释，导致 UTC 值被原样显示（比北京时间少 8 小时）；
 *   3. 纯日期字段（YYYY-MM-DD，如 install_date / due_date / validity_until）
 *      用 formatDateOnly 原样显示，不做时区换算。
 *
 * 兼容性：为兼容历史接口输出的 "2026-09-16 07:27:03" / "2026-09-16T07:27:03"
 * 等无时区标记写法，本模块先把字符串归一化为严格 ISO（空格→T、补 Z、截断微秒），
 * 浏览器才能稳定地按 UTC 解析。
 */

// 自动检测浏览器时区
const USER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** 字符串是否已带时区信息（Z 或 ±HH:MM / ±HHMM） */
function hasTimezone(s: string): boolean {
  return /([Zz]|[+-]\d{2}:?\d{2})$/.test(s);
}

/**
 * 归一化为严格 ISO-8601 UTC 字符串：
 * - 无时区标记 → 视为 UTC，补 "Z"（与后端 UTC 存储口径一致）；
 * - 空格分隔 → 换成 "T"（ES 规范只认 "T"，空格形式各浏览器解析结果不一致）；
 * - 小数秒超过 3 位（后端可能输出微秒）→ 截断到毫秒，避免部分浏览器判为 Invalid。
 */
function normalizeUtc(dateStr: string): string {
  let s = dateStr.trim();
  if (!hasTimezone(s)) s += 'Z';
  if (s.length > 10 && s[10] === ' ') s = `${s.slice(0, 10)}T${s.slice(11)}`;
  s = s.replace(/(\.\d{3})\d+/, '$1');
  return s;
}

/**
 * 将后端时间字符串解析为 Date（无时区标记一律按 UTC 处理）
 * 导出供需要自行取值的场景使用（如时间比较），显示请优先用下方格式化函数。
 */
export function toUtcDate(dateStr: string | null | undefined): Date | null {
  if (!dateStr) return null;
  const d = new Date(normalizeUtc(dateStr));
  return isNaN(d.getTime()) ? null : d;
}

/**
 * 使用浏览器本地时区格式化日期时间
 */
function formatWithTimezone(date: Date, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat('zh-CN', { timeZone: USER_TIMEZONE, ...options }).format(date);
}

/**
 * 将 UTC 时间字符串转换为本地时间格式
 * 输出格式：2026年6月22日 09:37
 */
export function formatDateTime(dateStr: string | null | undefined): string {
  const d = toUtcDate(dateStr);
  if (!d) return '-';
  return formatWithTimezone(d, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/**
 * 将 UTC 时间字符串转换为本地时间（含秒）
 * 输出格式：2026年6月22日 09:37:05
 */
export function formatDateTimeWithSeconds(dateStr: string | null | undefined): string {
  const d = toUtcDate(dateStr);
  if (!d) return '-';
  return formatWithTimezone(d, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/**
 * 将 UTC 时间字符串转换为本地时间（ISO 风格标准格式）
 * 输出格式：2026-09-16 15:27:03（按浏览器本地时区转换）
 * 用于表格/详情等需要 "YYYY-MM-DD HH:mm:ss" 数字格式的场景
 */
export function formatDateTimeStandard(dateStr: string | null | undefined): string {
  const d = toUtcDate(dateStr);
  if (!d) return '-';
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

/**
 * 将 UTC 时间字符串转换为本地日期
 * 输出格式：2026年6月22日
 */
export function formatDate(dateStr: string | null | undefined): string {
  const d = toUtcDate(dateStr);
  if (!d) return '-';
  return formatWithTimezone(d, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  });
}

/**
 * 纯日期字段原样显示（YYYY-MM-DD，不做时区换算）
 *
 * [统一时间口径] 后端 Date 类型字段（install_date / warranty_expire / validity_until /
 * due_date / inspection_date 等）本身即"北京业务日期"，不含时刻，不能按 UTC 偏移换算，
 * 否则会出现"日期差一天"。展示这类字段请统一使用本函数。
 */
export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return '-';
  const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : String(value);
}

/**
 * 相对时间显示（基于本地时区）
 * 刚刚 / N分钟前 / N小时前 / 昨天 / 具体日期
 */
export function timeAgo(dateStr: string | null | undefined): string {
  const d = toUtcDate(dateStr);
  if (!d) return '';
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  if (hours < 48) return '昨天';
  return formatDate(dateStr);
}
