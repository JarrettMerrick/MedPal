// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 全局品牌信息 Provider（单位名称 / 单位 Logo / 系统名称）。
 *
 * 设计：
 * - 单一数据源：全站（登录页、导航栏、工作台、系统设置页）统一消费本 context，
 *   避免各页面重复请求与拼接；
 * - 未配置时回退到内置默认值，行为与改造前完全一致（可安全回滚）；
 * - 启动即拉取（公开接口，无需登录）；保存品牌后调用 `refresh()` 立即全局生效；
 * - 同时负责动态更新浏览器标签标题（document.title）与页签图标（favicon）。
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getBranding, type BrandingInfo } from '../api/branding';

/** 系统名称未配置时的内置默认值（可在「系统设置」中自定义） */
export const DEFAULT_SYSTEM_NAME = '瑞慈医院医护信息管理';
/** 单位名称未配置时的展示文案（不再回退到任何内置品牌名） */
export const NOT_SET_TEXT = '未设置';

interface BrandingState {
  /** 是否正在加载（首屏为默认值，不阻塞渲染） */
  loading: boolean;
  /** 单位名称（未配置时显示「未设置」） */
  orgNameCn: string;
  orgNameEn: string;
  /** 系统名称（未配置时为内置默认值） */
  systemName: string;
  /**
   * 已解析的 Logo 地址：已配置时为 `/public/brand/...?v=<updated_at>`；
   * 未配置时为空字符串，展示方回退到内置默认 Logo。
   */
  logoUrl: string;
  /** 原始配置（供设置页展示/编辑） */
  raw: BrandingInfo | null;
  /** 重新拉取品牌信息（保存后调用，立即全局生效） */
  refresh: () => Promise<void>;
}

const BrandingContext = createContext<BrandingState>(null!);

export const useBranding = () => useContext(BrandingContext);

/** 捕获初始 favicon，重置 Logo 时用于恢复 */
const DEFAULT_FAVICON =
  typeof document !== 'undefined'
    ? document.querySelector('link[rel="icon"]')?.getAttribute('href') || '/vite.svg'
    : '/vite.svg';

/** 为 Logo 追加版本参数，双保险规避浏览器缓存（文件名本身已带内容哈希） */
function withVersion(url: string, updatedAt: string | null): string {
  if (!url) return '';
  if (!updatedAt) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}v=${encodeURIComponent(updatedAt)}`;
}

export const BrandingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [raw, setRaw] = useState<BrandingInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const info = await getBranding();
      setRaw(info);
    } catch (err) {
      // 拉取失败不阻塞页面：保持默认品牌，仅记录错误便于排查
      console.error('[branding] 获取品牌信息失败:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 单位名称未配置时统一显示「未设置」（不再回退到内置品牌名）
  const rawOrgNameCn = raw?.org_name_cn?.trim() || '';
  const rawOrgNameEn = raw?.org_name_en?.trim() || '';
  const orgNameCn = rawOrgNameCn || NOT_SET_TEXT;
  const orgNameEn = rawOrgNameEn || NOT_SET_TEXT;
  const systemName = raw?.system_name?.trim() || DEFAULT_SYSTEM_NAME;
  const logoUrl = useMemo(() => withVersion(raw?.logo_url || '', raw?.updated_at ?? null), [raw]);

  // 浏览器标签标题：仅在单位名称确有配置时才拼接，避免出现「未设置 · ...」
  const pageTitle = useMemo(
    () => (rawOrgNameCn && !systemName.includes(rawOrgNameCn) ? `${rawOrgNameCn} · ${systemName}` : systemName),
    [rawOrgNameCn, systemName],
  );

  // 动态更新标题与 favicon（登录页同样生效）
  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.title = pageTitle;
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.href = logoUrl || DEFAULT_FAVICON;
  }, [pageTitle, logoUrl]);

  const value: BrandingState = {
    loading,
    orgNameCn,
    orgNameEn,
    systemName,
    logoUrl,
    raw,
    refresh,
  };

  return <BrandingContext.Provider value={value}>{children}</BrandingContext.Provider>;
};
