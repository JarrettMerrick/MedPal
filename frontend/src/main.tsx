// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 应用入口文件。负责：
 * 1. 挂载 React 根组件到 DOM
 * 2. 注入外观偏好上下文（新拟物/经典 × 浅色/深色）
 * 3. 依据偏好动态构造并注入 Ant Design 主题（ConfigProvider + 中文国际化）
 * 4. 加载全局样式（拟物变量层 → Tailwind 基础 → Ant Design 覆盖）
 *
 * [改造 2026-09-19] 主题由静态改为**随偏好动态生成**：
 *   UiPrefsProvider 同时驱动两处 ——
 *     ① CSS 变量：通过 <html> 的 data-ui-style / data-color-mode 属性（见 UiPrefsContext）
 *     ② antd token：通过下文的 getAntdTheme() 注入 ConfigProvider
 *   两者同源，避免出现「组件样式变了、页面底色没变」的割裂。
 *
 * 数据流向：
 *   main.tsx → UiPrefsProvider → AppShell（读偏好 → getAntdTheme）
 *   → ConfigProvider(theme) → App → 路由 → 页面组件
 */

import React, { useMemo } from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App } from 'antd';
import zhCN from 'antd/locale/zh_CN'; // [改进] Ant Design 中文国际化
import AppRoot from './App';
// [改造 2026-09-19] 新拟物变量层：全站唯一视觉数值来源，必须最先导入，
// 供后续 styles / global / neumorphism 引用（默认值与改造前一致，不改变现有观感）
import './theme/neu-tokens.css';
import './styles/index.css';
import './theme/global.css'; // [改进] Ant Design 全局样式覆盖
import './theme/neumorphism.css'; // [改造 2026-09-19] 新拟物组件覆盖层（仅 neu 模式生效）
import { getAntdTheme } from './theme/antd-theme'; // [改造] 由 getAntdTheme 动态构造
import { UiPrefsProvider, useUiPrefs } from './contexts/UiPrefsContext';

/**
 * 应用外壳：读取外观偏好并构造主题。
 * 必须是 UiPrefsProvider 的子组件才能使用 useUiPrefs。
 */
const AppShell: React.FC = () => {
  const { uiStyle, colorMode } = useUiPrefs();
  // 偏好变化时重建主题对象；antd 内部按 token 值做差异处理，切换开销可控
  const theme = useMemo(
    () => getAntdTheme({ uiStyle, colorMode }),
    [uiStyle, colorMode],
  );

  return (
    <ConfigProvider theme={theme} locale={zhCN}>
      <App>
        <AppRoot />
      </App>
    </ConfigProvider>
  );
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <UiPrefsProvider>
      <AppShell />
    </UiPrefsProvider>
  </React.StrictMode>
);
