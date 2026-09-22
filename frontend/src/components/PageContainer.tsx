// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 页面统一内容容器（v1.1.0 布局系统）。
 * 负责收敛各页面的「内容最大宽度 + 居中 + 顶部留白」：
 * - 列表页：不传 maxWidth → 全宽自适应（默认）
 * - 表单页：maxWidth={800}（窄列，提升输入聚焦度）
 * - 详情页：maxWidth={960}（中列，图文混排阅读舒适）
 * - 个人中心：maxWidth={560}
 *
 * 使用方式：
 *   <PageContainer maxWidth={960}>...</PageContainer>
 * 内部自动 margin: 0 auto 居中；顶部留白与全局页面底对齐。
 */

import React from 'react';

interface PageContainerProps {
  /** 内容最大宽度；不传则全宽自适应 */
  maxWidth?: number;
  children: React.ReactNode;
}

const PageContainer: React.FC<PageContainerProps> = ({ maxWidth, children }) => {
  const style: React.CSSProperties = maxWidth
    ? { maxWidth, margin: '0 auto', width: '100%' }
    : { width: '100%' };

  return <div style={style}>{children}</div>;
};

export default PageContainer;
