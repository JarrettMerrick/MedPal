// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 站内信未读数 Provider（左侧「站内信」菜单红点 + 顶栏铃铛角标 + 站内信页内计数 的单一数据源）。
 *
 * [新增 2026-09-15] 需求：左侧「站内信」菜单显示未读数量（红点角标），
 * 并要求与顶栏铃铛、站内信页「未读」Tab 的计数完全一致。
 *
 * 设计要点（与 ReviewBadgeContext 同一套路，保证两类角标行为一致）：
 * - **单一数据源**：菜单红点、顶栏铃铛、站内信页内计数共同消费本 context；
 *   若各自拉取，会出现「菜单显示 3、铃铛显示 2」的口径不一致，且同一页面重复请求；
 * - **权限对齐**：仅对拥有 message.view 的账号发起请求（无权限必然 403，不做无效调用）；
 * - **刷新时机**：
 *     1) 登录态就绪后首拉；
 *     2) 30s 轮询（与顶栏铃铛原轮询间隔一致，合并后仍只有一处轮询）；
 *     3) 窗口重新聚焦（切回标签页立刻拿到最新数字，无需等待下一轮）；
 *     4) 站内信页 / 铃铛标记已读后直接 `setUnread`（本地递减）或 `refresh()`（与服务器对齐）；
 * - **失败静默**：未读数属辅助信息，单个接口失败仅保留上一次数值，不影响主流程；
 * - **退出清零**：登出后立刻归零，避免下一个登录账号短暂看到上一个人的未读数。
 */
import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react';
import { useAuth } from './AuthContext';
import { hasPermission, PERM_MESSAGE_VIEW } from '../utils/permissions';
import { getUnreadCount } from '../api/messages';

/** 轮询间隔（毫秒）：与顶栏铃铛原轮询保持一致 */
const POLL_INTERVAL = 30000;

interface MessageUnreadState {
  /** 未读站内信数量 */
  unread: number;
  /**
   * 直接写入权威数字：
   * - 收件箱接口响应里的 `unread`（服务端权威值）；
   * - 本地「标记一条已读后减 1」等即时反馈（避免为此多发一次请求）。
   */
  setUnread: React.Dispatch<React.SetStateAction<number>>;
  /** 立即重新拉取未读数（批量已读 / 删除 / 读取全部后调用，与服务器对齐） */
  refresh: () => Promise<void>;
}

const MessageUnreadContext = createContext<MessageUnreadState>({
  unread: 0,
  setUnread: () => {},
  refresh: async () => {},
});

export const useMessageUnread = () => useContext(MessageUnreadContext);

export const MessageUnreadProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isAuthenticated } = useAuth();
  const [unread, setUnread] = useState(0);

  // 权限判定：与菜单显隐、铃铛展示使用同一权限点，保证「能看到才去拉」
  const canViewMessages = hasPermission(user, PERM_MESSAGE_VIEW);

  // 防重入：轮询与窗口聚焦可能同时触发，避免并发请求交错写入造成数字抖动
  const inFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!isAuthenticated || !canViewMessages) return;
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const { count } = await getUnreadCount();
      setUnread(count);
    } catch {
      // 失败静默：保留上一次数值（角标属辅助信息）
    } finally {
      inFlightRef.current = false;
    }
  }, [isAuthenticated, canViewMessages]);

  // 登录态 / 权限变化时：拉取一次；未登录或无权限时清零（避免残留上一账号的未读数）
  useEffect(() => {
    if (!isAuthenticated || !canViewMessages) {
      setUnread(0);
      return;
    }
    refresh();
  }, [isAuthenticated, canViewMessages, refresh]);

  // 定时轮询
  useEffect(() => {
    if (!isAuthenticated || !canViewMessages) return;
    const timer = setInterval(() => { refresh(); }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [isAuthenticated, canViewMessages, refresh]);

  // 窗口重新聚焦（切回标签页 / 从其他应用返回）时立即刷新
  useEffect(() => {
    if (!isAuthenticated || !canViewMessages) return;
    const onFocus = () => { refresh(); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [isAuthenticated, canViewMessages, refresh]);

  return (
    <MessageUnreadContext.Provider value={{ unread, setUnread, refresh }}>
      {children}
    </MessageUnreadContext.Provider>
  );
};

export default MessageUnreadProvider;
