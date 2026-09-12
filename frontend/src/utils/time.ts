// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 时间显示工具函数
 * 后端统一存储 UTC 时间，前端根据浏览器本地时区自动转换显示
 *
 * 注意：后端通过 server_default=func.now() 或 datetime.now(timezone.utc) 存储的
 * 时间最终都是 UTC 时间，序列化为 JSON 时 naive datetime 不包含时区后缀。
 * JavaScript 的 new Date() 解析无时区标记的字符串时会当作本地时间，
 * 因此需要先补上 "Z" 标记为 UTC 再解析。
 */

// 自动检测浏览器时区
const USER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/**
 * 将时间字符串标准化为 UTC 解析
 * 无时区标记的字符串强制加 "Z"（视为 UTC），避免 JS 当作本地时间
 */
function toUtcDate(dateStr: string | null | undefined): Date | null {
  if (!dateStr) return null;
  // 如果字符串没有时区标记（Z 或 +/-偏移），手动补 Z 表示 UTC
  const hasTz = /[Zz]|[+-]\d{2}:\d{2}$/.test(dateStr);
  const normalized = hasTz ? dateStr : dateStr + 'Z';
  const d = new Date(normalized);
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
 * [新增 2026-09-08] 将 UTC 时间字符串转换为本地时间（ISO 风格标准格式）
 * 输出格式：2026-09-08 08:28:38（按浏览器本地时区转换）
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