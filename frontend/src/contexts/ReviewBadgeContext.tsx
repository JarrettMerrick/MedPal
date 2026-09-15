// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 待审核数量 Provider（「信息审核」菜单角标 + 页内 Tab 角标的单一数据源）。
 *
 * [新增 2026-09-15] 需求：左侧「信息审核」菜单显示未审核条数（红底白字），
 * 「信息审核」页面顶部的「账号注册审核」「信息变更审核」两个 Tab 采用同一原则。
 *
 * 设计要点：
 * - **单一数据源**：菜单与页内 Tab 共同消费本 context。若各自拉取，会出现
 *   「菜单显示 3、Tab 显示 2」的口径不一致，且同一页面重复请求两次；
 * - **权限对齐**：仅对拥有对应审核权限的账号发起请求（注册审核 user.approve /
 *   变更审核 staff.approve）。无权限就不请求，避免必然 403 的无效调用；
 * - **刷新时机**：
 *     1) 登录态就绪后首拉；
 *     2) 60s 轮询（与站内信铃铛同量级，兼顾实时性与服务端压力）；
 *     3) 窗口重新聚焦（切回标签页立刻拿到最新数字，无需等待下一轮）；
 *     4) 审核操作后由页面主动调用 `refresh()`（审核完一条角标立刻减少）；
 * - **失败静默**：角标属辅助信息，单个接口失败仅保留上一次数值，不影响主流程与
 *   另一个 Tab 的数字；
 * - **退出清零**：登出后立刻归零，避免下一个登录账号短暂看到上一个人的待办数。
 */
import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react';
import { useAuth } from './AuthContext';
import { hasPermission, PERM_STAFF_APPROVE, PERM_USER_APPROVE } from '../utils/permissions';
import { getRegistrationPendingCount } from '../api/registration';
import { getStaffChangePendingCount } from '../api/staffChanges';

/** 轮询间隔（毫秒） */
const POLL_INTERVAL = 60000;

interface ReviewBadgeState {
  /** 账号注册审核：待审数量 */
  registerCount: number;
  /** 信息变更审核：待审数量 */
  changeCount: number;
  /** 两项合计（菜单角标用；无权限的项按 0 计入） */
  total: number;
  /** 立即重新拉取（审核通过/驳回后调用，使菜单与 Tab 角标即时更新） */
  refresh: () => Promise<void>;
}

const ReviewBadgeContext = createContext<ReviewBadgeState>({
  registerCount: 0,
  changeCount: 0,
  total: 0,
  refresh: async () => {},
});

export const useReviewBadge = () => useContext(ReviewBadgeContext);

export const ReviewBadgeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isAuthenticated } = useAuth();
  const [registerCount, setRegisterCount] = useState(0);
  const [changeCount, setChangeCount] = useState(0);

  // 权限判定：与菜单显隐、Tab 显隐使用同一套权限点，保证「能看到才去拉」
  const canApproveRegister = hasPermission(user, PERM_USER_APPROVE);
  const canApproveChange = hasPermission(user, PERM_STAFF_APPROVE);

  // 防重入：轮询与窗口聚焦可能同时触发，避免并发请求交错写入造成数字抖动
  const inFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) return;
    // 两项权限都没有：无需请求（正常情况下也不会看到该菜单）
    if (!canApproveRegister && !canApproveChange) {
      setRegisterCount(0);
      setChangeCount(0);
      return;
    }
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const [reg, chg] = await Promise.all([
        // 单项失败返回 null，保留该 Tab 上一次的数值，不影响另一项刷新
        canApproveRegister ? getRegistrationPendingCount().catch(() => null) : Promise.resolve(null),
        canApproveChange ? getStaffChangePendingCount().catch(() => null) : Promise.resolve(null),
      ]);
      if (reg !== null) setRegisterCount(reg);
      if (chg !== null) setChangeCount(chg);
    } finally {
      inFlightRef.current = false;
    }
  }, [isAuthenticated, canApproveRegister, canApproveChange]);

  // 登录态 / 权限变化时：拉取一次；未登录时清零（避免残留上一账号的待办数）
  useEffect(() => {
    if (!isAuthenticated) {
      setRegisterCount(0);
      setChangeCount(0);
      return;
    }
    refresh();
  }, [isAuthenticated, refresh]);

  // 定时轮询
  useEffect(() => {
    if (!isAuthenticated) return;
    const timer = setInterval(() => { refresh(); }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [isAuthenticated, refresh]);

  // 窗口重新聚焦（切回标签页 / 从其他应用返回）时立即刷新
  useEffect(() => {
    if (!isAuthenticated) return;
    const onFocus = () => { refresh(); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [isAuthenticated, refresh]);

  const value: ReviewBadgeState = {
    registerCount,
    changeCount,
    total: registerCount + changeCount,
    refresh,
  };

  return <ReviewBadgeContext.Provider value={value}>{children}</ReviewBadgeContext.Provider>;
};

export default ReviewBadgeProvider;
