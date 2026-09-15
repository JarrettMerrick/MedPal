// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 全局功能开关 Provider（系统设置 → 功能开关）。
 *
 * 设计：
 * - 单一数据源：菜单、页面入口、顶部铃铛等统一消费本 context，避免各处重复请求；
 * - 走**公开**接口（免登录），登录页与强制改密阶段同样可用；
 * - 拉取失败时保持「全部启用」：一次网络异常不应把所有入口藏掉；
 * - 设置页保存后调用 `refresh()` 立即全局生效。
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { getFeatureFlags, type FeatureFlags, type FeatureKey } from '../api/features';

/** 默认全部启用（与后端默认值一致，且接口失败时兜底） */
const DEFAULT_FLAGS: FeatureFlags = { messages: true, signage: true, regulation: true };

interface FeaturesState {
  /** 各功能是否启用 */
  flags: FeatureFlags;
  /** 是否正在加载（首屏为默认值，不阻塞渲染） */
  loading: boolean;
  /** 便捷判断：未显式返回 false 即视为启用 */
  isEnabled: (key: FeatureKey) => boolean;
  /** 重新拉取（设置页保存后调用，立即全局生效） */
  refresh: () => Promise<void>;
}

const FeaturesContext = createContext<FeaturesState>(null!);

export const useFeatures = () => useContext(FeaturesContext);

export const FeaturesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [flags, setFlags] = useState<FeatureFlags>(DEFAULT_FLAGS);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await getFeatureFlags();
      // 合并默认值：后端新增功能时，前端不会因缺字段而判为关闭
      setFlags({ ...DEFAULT_FLAGS, ...data });
    } catch (err) {
      // 拉取失败不阻塞页面：保持「全部启用」，仅记录错误便于排查
      console.error('[features] 获取功能开关失败:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value: FeaturesState = {
    flags,
    loading,
    isEnabled: (key: FeatureKey) => flags[key] !== false,
    refresh,
  };

  return <FeaturesContext.Provider value={value}>{children}</FeaturesContext.Provider>;
};
