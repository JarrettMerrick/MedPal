// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import axios from 'axios';
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

// ---- Request 拦截器 ----
api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---- Response 拦截器（含静默刷新） ----
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // 仅对 401 且非刷新请求自身触发静默刷新
    if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/auth/refresh')) {
      if (isRefreshing) {
        // 已有刷新进行中，排队等待结果
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const newToken = await tryRefreshToken();
      if (newToken) {
        processQueue(null, newToken);
        isRefreshing = false;
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
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

export default api;

/** 创建上传专用的 axios 实例（5分钟超时，同样支持静默刷新） */
export const uploadApi = axios.create({
  baseURL: '/api',
  timeout: 300000,
  // [修复/问题3] 同上：分片上传实例同样携带 Cookie
  withCredentials: true,
});

uploadApi.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

uploadApi.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/auth/refresh')) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return uploadApi(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const newToken = await tryRefreshToken();
      if (newToken) {
        processQueue(null, newToken);
        isRefreshing = false;
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return uploadApi(originalRequest);
      }

      processQueue(new Error('refresh_failed'), null);
      isRefreshing = false;
      logoutAndRedirect();
      return Promise.reject(error);
    }
    return Promise.reject(error);
  }
);
