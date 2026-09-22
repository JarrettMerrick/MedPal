// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import axios from 'axios';
// [新增 2026-09-21 / Q-11、Q-12] 提取公共拦截器注册函数需要实例类型；
// 错误处理收敛 any 后需要 AxiosError 类型做收窄
import type { AxiosInstance, AxiosError } from 'axios';
import { getAccessToken, setAccessToken, setFileToken, clearTokens, clearSessionHint } from '../utils/tokenStore';

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
  // [修复/问题3] 携带 Cookie（refresh_token 位于 HttpOnly Cookie）：
  // 同源部署下无副作用；跨域/独立端口部署时用于让浏览器把 Cookie 一并发送。
  withCredentials: true,
});

// ---- Token 刷新状态管理 ----
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error);
    } else {
      resolve(token!);
    }
  });
  failedQueue = [];
};

const logoutAndRedirect = () => {
  // [修复/问题3] 令牌不再落地 localStorage，只需清理内存
  clearTokens();
  clearSessionHint();
  // 兼容历史版本：清除旧版本曾写入 localStorage 的残留令牌
  try {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('file_token');
    localStorage.removeItem('user');
  } catch {
    /* 忽略：部分浏览器隐私模式下 localStorage 不可用 */
  }
  // 避免重复跳转
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
};

/**
 * [修复/问题3 + 问题11] 静默刷新令牌
 *
 * refresh_token 现由后端以 HttpOnly Cookie 下发，前端无法读取，
 * 因此这里不再从 localStorage 取值，而是依靠 withCredentials 让浏览器自动携带 Cookie。
 * 后端刷新时会轮换 refresh_token 并把旧令牌加入黑名单（复用即判定为盗用并拒绝），
 * 返回的 access_token / file_token 仅写入内存。
 */
const tryRefreshToken = async (): Promise<string | null> => {
  try {
    const response = await axios.post(
      '/api/auth/refresh',
      {},
      { withCredentials: true },
    );
    const newAccessToken = response.data.access_token;
    if (!newAccessToken) return null;
    setAccessToken(newAccessToken);
    if (response.data.file_token) {
      setFileToken(response.data.file_token);
    }
    return newAccessToken;
  } catch {
    return null;
  }
};

/**
 * [修复 2026-09-17] 把 FastAPI 的 422 校验错误转成可读字符串。
 *
 * Pydantic 校验失败时 detail 是数组：
 *   [{loc: ["body","group_name"], msg: "Input should be a valid string", type: "..."}]
 * 各页面普遍按 `e.response.data.detail || '默认文案'` 使用，数组会被渲染成
 * [object Object]（或直接取不到信息），用户只看到"操作失败"而不知原因。
 * 这里就地改写为「字段: 原因；字段: 原因」，全站错误提示立即变得可读。
 */
// [改进 2026-09-21 / 代码质量审计 Q-12] 把 any 收敛为 unknown + 显式收窄。
// 原签名 `error: any` 使整个函数体的属性访问都失去编译期保护 —— 例如把
// `data.detail` 误写成 `data.deatil` 也不会报错，只会在运行时静默失效
// （用户看到"操作失败"却查不出原因）。现在每一步访问都需要先证明类型。
function normalizeErrorDetail(error: unknown): void {
  const data = (error as AxiosError<{ detail?: unknown }> | undefined)?.response?.data;
  if (!data || !Array.isArray(data.detail)) return;

  const text = (data.detail as unknown[])
    .map((item) => {
      const rec = item as { loc?: unknown; msg?: unknown };
      const loc = Array.isArray(rec.loc)
        ? (rec.loc as unknown[]).filter(
            (key) => key !== 'body' && key !== 'query' && key !== 'path',
          )
        : [];
      const field = loc.length ? loc.join('.') : '';
      const msg = typeof rec.msg === 'string' ? rec.msg : '';
      if (!msg) return '';
      return field ? `${field}: ${msg}` : msg;
    })
    .filter(Boolean)
    .join('；');
  // 就地改写 detail（保持既有调用方 `e.response.data.detail || '默认文案'` 的用法不变）
  (data as { detail?: unknown }).detail = text || '请求参数有误';
}

/**
 * 从任意异常中提取可直接展示给用户的错误文案。
 *
 * [新增 2026-09-21 / 代码质量审计 Q-12] 此前各页面普遍写成
 * `e.response?.data?.detail || '操作失败'` —— 问题在于 `e` 多为 `any`，
 * 一旦后端字段改名（detail → message）或返回结构变化，这些取值会**静默**变成
 * 兜底文案，用户只看到"操作失败"，排查时也无从下手。
 *
 * 统一走本函数后：类型在编译期受保护，且 422 的数组 detail 已在拦截器里
 * 被 normalizeErrorDetail 转成可读字符串，这里只需按顺序尝试几处取值。
 */
export function getErrorMessage(error: unknown, fallback = '操作失败'): string {
  // 网络层错误（无 response）：区分"连不上"与"已发出但无响应"
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (error.response?.status === 401) return '登录状态已失效，请重新登录';
    if (error.response?.status === 403) return '没有执行该操作的权限';
    if (error.response?.status === 404) return '请求的资源不存在';
    if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试';
    if (!error.response) return '网络连接失败，请检查网络后重试';
  }
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return fallback;
}

/**
 * 为指定 axios 实例注册认证相关的请求/响应拦截器。
 *
 * [重构 2026-09-21 / 代码质量审计 Q-11] 原先 `api` 与 `uploadApi` 各自写了一份
 * **逐行相同**的拦截器（各约 40 行，仅 `api(` / `uploadApi(` 一字的差别）。
 * 两份维护的风险很具体：令牌静默刷新的排队与重放逻辑一旦只改一处，
 * 另一个实例的 401 行为就会与它不一致 —— 例如一处实现了并发排队、
 * 另一处没有，会导致同时发起多个刷新请求、拿到旧令牌或反复登出。
 *
 * 抽取时把"重放请求用哪个实例"参数化为 `instance`，其余逻辑完全一致。
 *
 * @param instance 需要挂载拦截器的 axios 实例（api 或 uploadApi）
 */
function registerAuthInterceptors(instance: AxiosInstance): void {
  // ---- Request 拦截器：附加 Bearer 令牌 ----
  instance.interceptors.request.use((config) => {
    const token = getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // ---- Response 拦截器（含静默刷新） ----
  instance.interceptors.response.use(
    (response) => response,
    async (error) => {
      const originalRequest = error.config;

      // [修复 2026-09-17] 先统一转换 422 校验错误（数组 → 可读文案），再走其它错误分支
      normalizeErrorDetail(error);

      // 仅对 401 且非刷新请求自身触发静默刷新
      if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/auth/refresh')) {
        if (isRefreshing) {
          // 已有刷新进行中，排队等待结果
          return new Promise((resolve, reject) => {
            failedQueue.push({ resolve, reject });
          }).then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return instance(originalRequest);
          });
        }

        originalRequest._retry = true;
        isRefreshing = true;

        const newToken = await tryRefreshToken();
        if (newToken) {
          processQueue(null, newToken);
          isRefreshing = false;
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return instance(originalRequest);
        }

        // 刷新失败，登出
        processQueue(new Error('refresh_failed'), null);
        isRefreshing = false;
        logoutAndRedirect();
        return Promise.reject(error);
      }

      // 非 401 错误直接抛出
      return Promise.reject(error);
    }
  );
}

registerAuthInterceptors(api);

export default api;

/** 创建上传专用的 axios 实例（5分钟超时，同样支持静默刷新） */
export const uploadApi = axios.create({
  baseURL: '/api',
  timeout: 300000,
  // [修复/问题3] 同上：分片上传实例同样携带 Cookie
  withCredentials: true,
});

// [重构 2026-09-21 / Q-11] 复用同一套拦截器逻辑，替代原先约 40 行的重复实现。
// 行为与原实现完全一致（含 422 文案归一化与静默刷新排队），只是不再有两份代码。
registerAuthInterceptors(uploadApi);
