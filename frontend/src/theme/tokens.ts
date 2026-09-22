// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 语义化设计 token 工具，统一替换散落在各页面中的硬编码样式。
 * 所有值对齐 Ant Design 5.x 官方设计规范，确保主题 ConfigProvider 真正生效。
 *
 * 使用方式：
 * 1. 间距优先用 <Space>/<Flex>/<Row gutter> 组件
 * 2. 颜色优先用 Text type="secondary" / Tag color / colorPrimary 等语义 token
 * 3. 本文件仅导出「无法用组件表达」时的兜底常量
 *
 * 数据流向：tokens → 各页面内联样式替换 → 视觉统一
 */

import type { ThemeConfig } from 'antd';

/**
 * 8px 基础网格间距（对齐 antd margin/padding token）
 * xs=8, sm=12, md=16, lg=24, xl=32
 */
export const SPACING = {
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
} as const;

/** 圆角梯度（对齐 antd borderRadius token，v1.1.0 升级：lg 12 / base 8 / sm 6） */
export const RADIUS = {
  sm: 6, // 小元素 Tag/Button
  base: 8, // 全局默认
  lg: 12, // 大容器 Card/Modal
} as const;

/**
 * 品牌色（医疗青蓝体系）
 * 与 antd-theme.ts 保持一致，供内联样式兜底使用。
 */
export const BRAND = {
  /** 主色 - 医疗青蓝 */
  primary: '#0E7F8A',
  /** 主色悬浮 */
  primaryHover: '#1B8E99',
  /** 主色按下 */
  primaryActive: '#0A6771',
  /** 主色浅底 */
  primaryBg: '#E3F4F6',
  /** 主色浅底悬浮 */
  primaryBgHover: '#D6EEF1',
  /** 主色浅边框 */
  primaryBorder: '#9AD0D6',
} as const;

/**
 * 中性色（暖灰底 + 层级文字）
 */
export const NEUTRAL = {
  /** 页面底色（暖灰） */
  bgLayout: '#F6F8FA',
  /** 主文字（深蓝灰） */
  text: '#1F2D3D',
  /** 次级文字 */
  textSecondary: '#5C6B7A',
  /** 弱文字 */
  textTertiary: '#8A97A6',
  /** 主要边框 */
  border: '#E3E8EE',
  /** 次级边框/分割线 */
  borderSecondary: '#EDF0F3',
} as const;

/**
 * 角色徽章配色（改用 antd Tag 语义色，替代硬编码 hex）
 * 原：admin_manager 红、dept_manager 橙、employee 灰
 */
export const ROLE_TAG_COLOR: Record<string, string> = {
  admin_manager: 'red',
  dept_manager: 'orange',
  employee: 'default',
};

/**
 * 页面布局规范（v1.1.0 布局系统，2026-08-07 新增）
 * ============
 * 统一全站页面容器宽度、页面头部间距、卡片/栅格间距，
 * 作为各页面布局的唯一来源，避免散落的硬编码间距。
 *
 * 规则：
 * - 列表页：全宽自适应（不传 maxWidth）
 * - 表单页：窄列 800
 * - 详情页：中列 960
 * - 个人中心：560
 * - 卡片纵向堆叠间距 16、栅格间距 16、头部下距 24
 */
export const LAYOUT = {
  /** 页面头部：返回按钮与标题间距 / 标题与内容间距 */
  HEADER: { gap: 12, marginBottom: 24 },
  /** 卡片纵向堆叠 / 栅格间距（8px 网格的两倍） */
  CARD_GAP: 16,
  /** 窄列内容最大宽度（列表页全宽，无需设置） */
  WIDTH: { form: 800, detail: 960, profile: 560 },
  /** 表单输入控件建议最大宽度（避免窄列内输入框过长） */
  FORM_MAX_WIDTH: 480,
} as const;

/** 页面头部 Title 的统一底部间距（对齐 LAYOUT.HEADER.marginBottom） */
export const PAGE_HEADER_MARGIN = LAYOUT.HEADER.marginBottom;

/**
 * 在 antd-theme.ts 中补充的组件级 token（使默认样式即合规，减少代码层硬编码）
 */
export const EXTRA_THEME: Partial<ThemeConfig> = {
  components: {
    Card: {
      borderRadiusLG: RADIUS.lg,
    },
    // [修复 2026-09-05] antd v5 组件配置中不存在 Title 键（TS2353），
    // 标题间距由 Typography 组件 token 控制
    Typography: {
      titleMarginTop: 0,
    },
  },
};
