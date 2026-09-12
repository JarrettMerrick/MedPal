// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import type { UserInfo } from '../types/user';
import { login as apiLogin, getMe, logout as apiLogout } from '../api/auth';
import { getAccessToken, setAccessToken, setFileToken, clearTokens, hasSessionHint, clearSessionHint } from '../utils/tokenStore';

interface AuthState {
  user: UserInfo | null;
  token: string | null;
  isAuthenticated: boolean;
  isFirstLogin: boolean;
  isLoading: boolean;
  login: (employeeId: string, password: string, rememberMe?: boolean) => Promise<void>;
  logout: () => void;
  setUser: (user: UserInfo) => void;
}

const AuthContext = createContext<AuthState>(null!);

export const useAuth = () => useContext(AuthContext);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [token, setToken] = useState<string | null>(getAccessToken());
  // [修复/问题3] 启动即处于加载态：需先尝试静默恢复会话，
  // 避免在刷新页面时短暂闪现登录页。
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;

    /**
     * [修复/问题3] access_token 只保存在内存中，刷新页面后必然为空，
     * 因此不能用 localStorage 里的令牌来恢复登录态。
     * 改为：以 HttpOnly Cookie 中的 refresh_token 调 /auth/refresh 静默换新，
     * 成功后用新 access_token 再拉取 /auth/me。
     * 未登录时该请求会 401，被 catch 后落到未登录态。
     */
    const bootstrap = async () => {
      // [改进] 没有会话提示 Cookie 说明几乎不可能已登录，
      // 直接判定未登录，避免发起一次必然 401 的 /auth/refresh 探测（登录页噪音）
      if (!hasSessionHint()) {
        setIsLoading(false);
        return;
      }
      try {
        const res = await axios.post('/api/auth/refresh', {}, { withCredentials: true });
        const accessToken = res.data?.access_token;
        if (!accessToken) {
          if (!cancelled) setIsLoading(false);
          return;
        }
        setAccessToken(accessToken);
        if (res.data?.file_token) setFileToken(res.data.file_token);
        if (cancelled) return;
        setToken(accessToken);
        const me = await getMe();
        if (cancelled) return;
        setUser(me);
      } catch {
        clearTokens();
        // 刷新失败（过期/已失效）时一并移除会话提示，避免后续反复探测
        clearSessionHint();
        if (!cancelled) {
          setToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (employeeId: string, password: string, rememberMe: boolean = false) => {
    const res = await apiLogin(employeeId, password, rememberMe);
    // [修复/问题3] access_token / file_token 仅写入内存；refresh_token 由后端
    // 以 HttpOnly Cookie 下发，前端既不读取也不落盘，XSS 无法窃取长期凭据。
    setAccessToken(res.access_token);
    if (res.file_token) setFileToken(res.file_token);
    setToken(res.access_token);
    setUser(res.user);
  };

  const logout = () => {
    // refresh_token 位于 HttpOnly Cookie，后端登出接口会自行读取并吊销/清除，
    // 这里只需把当前 access_token 传过去加入黑名单。
    apiLogout(undefined, getAccessToken() ?? undefined).catch(() => {
      // 即使 API 调用失败，也继续清理本地令牌
    });
    clearTokens();
    clearSessionHint();
    setToken(null);
    setUser(null);
    setIsLoading(false);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token && !!user,
        isFirstLogin: !!user?.must_change_password,
        isLoading,
        login,
        logout,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
