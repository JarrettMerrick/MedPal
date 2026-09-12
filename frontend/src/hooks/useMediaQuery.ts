// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 响应式媒体查询 Hook，用于监听 CSS 媒体查询变化。
 * 替代 Layout 中手动监听 window.resize 的内联逻辑，统一断点管理。
 * 
 * 数据流向：CSS media query → matchMedia → React state → 消费方
 */

import { useEffect, useState } from 'react';

/**
 * 响应式媒体查询 Hook
 * @param query - CSS 媒体查询字符串，如 '(max-width: 991px)'
 * @returns 是否匹配当前视口
 * 
 * @example
 * const isMobile = useMediaQuery('(max-width: 991px)');
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    // SSR 兼容：服务端渲染默认返回 false
    if (typeof window === 'undefined') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);

    // 现代浏览器使用 addEventListener
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

export default useMediaQuery;
