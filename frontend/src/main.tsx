// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 应用入口文件。负责：
 * 1. 挂载 React 根组件到 DOM
 * 2. 注入 Ant Design 5.x ConfigProvider（全局主题 + 中文国际化）
 * 3. 加载全局样式（Tailwind + Ant Design 微调）
 * 
 * 数据流向：main.tsx → ConfigProvider(theme) → App → 路由 → 页面组件
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App } from 'antd';
import zhCN from 'antd/locale/zh_CN'; // [改进] Ant Design 中文国际化
import AppRoot from './App';
import './styles/index.css';
import './theme/global.css'; // [改进] Ant Design 全局样式覆盖
import theme from './theme/antd-theme'; // [改进] 统一主题配置

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider theme={theme} locale={zhCN}>
      <App>
        <AppRoot />
      </App>
    </ConfigProvider>
  </React.StrictMode>
);
