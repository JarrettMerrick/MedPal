// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 功能开关路由守卫（[新增 2026-09-17]）。
 *
 * 背景：单位级「系统设置 → 功能开关」原先只作用于左侧菜单与顶部铃铛，
 * 关闭某个模块后**直接输入 URL 仍能进入对应页面**（页面正常渲染并触发一串 403 请求），
 * 与「关闭即不可用」的预期不符。
 *
 * 处理：按**路径前缀**把路由归入所属功能模块，开关关闭时统一重定向到工作台。
 * 采用前缀映射而非逐条路由挂载 feature 参数，好处是同一模块新增页面时
 * 无需再逐个补参数，避免再次遗漏。权限校验仍由各路由自身的 RoleGuard 负责
 * （两者同时通过才放行，与菜单的两层门禁口径一致）。
 */
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { useFeatures } from '../contexts/FeaturesContext';
import type { FeatureKey } from '../api/features';

/**
 * 路径前缀 → 所属功能开关。
 *
 * 顺序说明：`/signage` 为前缀匹配，可覆盖 /signages、/signage-overview、
 * /signage-mobile、/signage-floorplan 等全部标识平面页面；
 * 「标识设置」下的院区管理 / 平面设置 / 标识分类（/signage-categories）/
 * 供应商设置同属 `signage` 开关（与后端 FEATURE_META 的表述一致）。
 */
const FEATURE_PATH_PREFIXES: Array<{ prefix: string; feature: FeatureKey }> = [
  // 「标识平面 + 标识设置」由同一个开关控制
  { prefix: '/signage', feature: 'signage' },
  { prefix: '/design-files', feature: 'signage' },        // 文件管理：标识设计文件库
  { prefix: '/campus-management', feature: 'signage' },   // 院区管理
  { prefix: '/suppliers', feature: 'signage' },           // 供应商设置
  // 制度牌
  { prefix: '/regulations', feature: 'regulation' },
  // 站内信
  { prefix: '/messages', feature: 'messages' },
];

const FeatureRouteGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { pathname } = useLocation();
  const { isEnabled } = useFeatures();

  const hit = FEATURE_PATH_PREFIXES.find((item) => pathname.startsWith(item.prefix));
  if (hit && !isEnabled(hit.feature)) {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
};

export default FeatureRouteGuard;
