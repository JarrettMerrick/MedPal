// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 令牌内存存储（对应审计问题 3 / 问题 11）
 *
 * 背景：原先 access_token、refresh_token、file_token 均明文写入 localStorage。
 * 任何一处 XSS（例如富文本渲染链路）都能直接读取 refresh_token 并外传，
 * 从而长期反复换发 access_token，完全接管账户。
 *
 * 改造后：
 *   - refresh_token：由后端以 HttpOnly + SameSite=Lax Cookie 下发，前端 JS 不可读；
 *   - access_token / file_token：仅保存在本模块的变量中（内存），
 *     刷新页面即丢失，由后端 Cookie 静默换新恢复会话；
 *   - localStorage 中不再保存任何令牌，XSS 无法再窃取长期凭据。
 */
let accessToken: string | null = null;
let fileToken: string | null = null;

export const getAccessToken = (): string | null => accessToken;

export const setAccessToken = (token: string | null): void => {
  accessToken = token;
};

export const getFileToken = (): string | null => fileToken;

export const setFileToken = (token: string | null): void => {
  fileToken = token;
};

export const clearTokens = (): void => {
  accessToken = null;
  fileToken = null;
};

/**
 * 会话提示 Cookie 名（与后端 auth.py 的 SESSION_HINT_COOKIE 保持一致）。
 * 非 HttpOnly，仅存常量 "1"，用于让前端判断"是否可能已有会话"。
 */
const SESSION_HINT_COOKIE = 'mp_session';

/** 是否存在会话提示：无提示时无需调用 /auth/refresh，避免必然的 401 噪音 */
export const hasSessionHint = (): boolean =>
  typeof document !== 'undefined' &&
  document.cookie.split('; ').some((c) => c.startsWith(`${SESSION_HINT_COOKIE}=`));

/** 清除会话提示 Cookie（登出时兜底，后端也会下发删除指令） */
export const clearSessionHint = (): void => {
  if (typeof document === 'undefined') return;
  document.cookie = `${SESSION_HINT_COOKIE}=; Max-Age=0; path=/; SameSite=Lax`;
};
