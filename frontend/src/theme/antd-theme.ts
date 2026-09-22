// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 本文件为 Ant Design 5.x 全局主题配置工厂，通过 ConfigProvider 注入整个应用。
 *
 * [改造 2026-09-19] 由「静态 theme 对象」改为「getAntdTheme(options) 工厂函数」：
 *   外观风格（新拟物 / 经典）与明暗模式（浅色 / 深色）由 UiPrefsContext 驱动，
 *   本函数据此返回对应的 ThemeConfig，与 CSS 变量层（neu-tokens.css）**同步切换**。
 *   若只改其一，会出现「组件样式变了、页面底色没变」的割裂，因此两者必须同源：
 *   同一个 UiPrefs 状态既喂给本函数，又写入 <html> 属性。
 *
 * 设计原则（v1.1.0 UI 精致化，2026-08-07；2026-09-19 追加拟物支持）：
 * - 主色为 #0E7F8A（医疗青蓝），符合医院「信任、洁净、安宁」的气质；
 *   深色下提亮为 #2FB3C0，保证在深底上的对比度（与 --accent 保持同值）。
 * - 新拟物的成立前提是**表面与页面底同色**：拟物模式下 colorBgLayout 与
 *   colorBgContainer 归一（浅色 #E8EBF2 / 深色 #262E33），
 *   立体感全部交由 CSS 的双向柔和阴影表达（见 neumorphism.css）。
 * - 经典模式保留改造前的取值（暖灰页底 + 白色容器 + 细边框），保证可回退。
 *
 * 数据流向：UiPrefsContext.state → getAntdTheme() → ConfigProvider → 全应用生效
 */

import { theme as antdTheme } from 'antd';
import type { ThemeConfig } from 'antd';
import type { ColorMode, UiStyle } from '../contexts/UiPrefsContext';

export interface AntdThemeOptions {
  /** 外观风格：neu = 新拟物，classic = 经典（改造前样式） */
  uiStyle: UiStyle;
  /** 明暗模式 */
  colorMode: ColorMode;
}

/**
 * 构建 Ant Design 主题配置。
 *
 * 组合出四种外观：新拟物/经典 × 浅色/深色。
 * 其中「经典 + 浅色」的取值与改造前**逐项一致**，确保回退时观感完全还原。
 */
export function getAntdTheme({ uiStyle, colorMode }: AntdThemeOptions): ThemeConfig {
  const isNeu = uiStyle === 'neu';
  const isDark = colorMode === 'dark';

  // ── 品牌色：深色下提亮，保证主操作在深底上依然醒目 ──
  const primary = isDark ? '#2FB3C0' : '#0E7F8A';
  const primaryHover = isDark ? '#46C4D0' : '#1B8E99';
  const primaryActive = isDark ? '#1A9AA6' : '#0A6771';
  const primaryBg = isDark ? 'rgba(47,179,192,0.16)' : '#E3F4F6';
  const primaryBgHover = isDark ? 'rgba(47,179,192,0.24)' : '#D6EEF1';
  const primaryBorder = isDark ? 'rgba(47,179,192,0.42)' : '#9AD0D6';

  // ── 中性色 ──
  // 拟物模式：页面底与容器**同色**（立体感来自阴影，而非底色差）
  // 经典模式：保留改造前的「暖灰页底 + 白色容器」
  const pageBg = isNeu
    ? isDark
      ? '#262E33'
      : '#E8EBF2'
    : isDark
      ? '#16191C'
      : '#F6F8FA';
  const containerBg = isNeu ? pageBg : isDark ? '#1F2529' : '#FFFFFF';

  // 三级文字 —— [统一方案 2026-09-19] 按 WCAG 2.1 实测定值。
  // 关键变化：**不再区分「拟物 / 经典」**。此前同一个语义在两套模式下给出不同色值
  // （如 tertiary 拟物 #6B7A8A、经典 #8A97A6），是"不同页面文字深浅不一致"的根源；
  // 现统一为一组值，与 neu-tokens.css 的 --text-1/2/3 完全对应。
  //
  //   层级            浅色      深色      实测对比度（浅底 #F6F8FA / #E7EEF1）
  //   textPrimary   #16232E   #EEF4F7   15.01 / 13.62  AAA
  //   textSecondary #3F5162   #B8C7D1    7.69 /  6.98  AA+
  //   textTertiary  #5B6A78   #93A2AE    5.22 /  4.74  AA
  //                                    （原 #8A97A6 仅 2.79，严重偏浅）
  const textPrimary = isDark ? '#EEF4F7' : '#16232E';
  const textSecondary = isDark ? '#B8C7D1' : '#3F5162';
  const textTertiary = isDark ? '#93A2AE' : '#5B6A78';

  // 分界与填充：拟物模式取消实线边框，改用极浅同色分界
  const borderColor = isDark
    ? 'rgba(255,255,255,0.09)'
    : isNeu
      ? 'rgba(122,152,165,0.22)'
      : '#E3E8EE';
  const borderSecondary = isDark
    ? 'rgba(255,255,255,0.05)'
    : isNeu
      ? 'rgba(122,152,165,0.12)'
      : '#EDF0F3';
  const fillQuaternary = isDark ? 'rgba(255,255,255,0.06)' : isNeu ? '#DFE7EB' : '#F1F4F7';

  // 表头/菜单等浅底：拟物下与底色同源，仅靠轻微凹陷区分（见 neumorphism.css）
  const subtleBg = isDark ? (isNeu ? '#262E33' : '#1F2529') : isNeu ? '#E8EBF2' : '#F8FAFB';
  const hoverBg = isDark ? 'rgba(47,179,192,0.12)' : isNeu ? '#DCE6EA' : '#F0F8F9';

  // 阴影：拟物用双向柔和阴影，经典沿用现有单向阴影
  const shadow = isNeu
    ? isDark
      ? '6px 6px 14px rgba(0,0,0,0.45), -6px -6px 14px rgba(255,255,255,0.07)'
      : '6px 6px 14px rgba(122,152,165,0.33), -6px -6px 14px rgba(255,255,255,0.76)'
    : '0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)';
  const shadowSecondary = isNeu
    ? isDark
      ? '16px 16px 36px rgba(0,0,0,0.55), -16px -16px 36px rgba(255,255,255,0.06)'
      : '16px 16px 36px rgba(122,152,165,0.33), -16px -16px 36px rgba(255,255,255,0.76)'
    : '0 12px 32px rgba(16,24,40,.10)';

  // 圆角：拟物偏大，强化柔软触感
  const radiusBase = isNeu ? 12 : 8;
  const radiusLG = isNeu ? 20 : 12;
  const radiusSM = isNeu ? 10 : 6;

  return {
    // 深色使用 antd 官方暗色算法作为基底，再由下方 token 覆写为拟物取值
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,

    token: {
      // ========== 品牌主色（青蓝体系，深色下提亮） ==========
      colorPrimary: primary,
      colorPrimaryHover: primaryHover,
      colorPrimaryActive: primaryActive,
      colorPrimaryBg: primaryBg,
      colorPrimaryBgHover: primaryBgHover,
      colorPrimaryBorder: primaryBorder,
      colorLink: primary,

      // ========== 功能色 ==========
      colorSuccess: isDark ? '#3FCA77' : '#16A34A',
      colorWarning: isDark ? '#F4A83A' : '#F59E0B',
      colorError: isDark ? '#F87171' : '#EF4444',
      colorInfo: primary,

      // ========== 中性色 ==========
      colorBgLayout: pageBg,
      colorBgContainer: containerBg,
      /** 浮层（弹窗 / 下拉 / 抽屉）底色：拟物下与容器同色，靠阴影浮起 */
      colorBgElevated: isDark ? '#2C353B' : isNeu ? '#E8EBF2' : '#FFFFFF',
      colorBorder: borderColor,
      colorBorderSecondary: borderSecondary,
      colorText: textPrimary,
      colorTextSecondary: textSecondary,
      colorTextTertiary: textTertiary,
      colorFillQuaternary: fillQuaternary,
      /** 占位符与禁用文字：[统一方案] 与 --text-placeholder 一致。
          占位符豁免 AA 对比度要求（属临时提示），但仍保证可辨识（约 2.8:1）；
          原经典浅色 #B3BDC7 仅 1.79:1，几乎看不清。 */
      colorTextPlaceholder: isDark ? '#7F8D99' : '#8B98A6',

      // ========== 字体 ==========
      fontFamily: `"PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif`,
      fontSize: 14,

      // ========== 形状与阴影 ==========
      borderRadius: radiusBase,
      borderRadiusLG: radiusLG,
      borderRadiusSM: radiusSM,
      boxShadow: shadow,
      boxShadowSecondary: shadowSecondary,

      padding: 16,
      margin: 16,
    },

    components: {
      Layout: {
        /** 侧边栏 / 顶栏与页面底同源（拟物下同色，经典下白色） */
        siderBg: containerBg,
        headerBg: containerBg,
        headerHeight: 56,
        /** 内容区背景跟随页面底，避免出现色块断层 */
        bodyBg: pageBg,
      },
      Menu: {
        itemBg: 'transparent',
        itemSelectedBg: primaryBg,
        itemSelectedColor: primary,
        itemHoverBg: hoverBg,
        itemBorderRadius: isNeu ? 12 : 8,
        itemHeight: 44,
        iconMarginInlineEnd: 10,
        subMenuItemBg: 'transparent',
        groupTitleColor: textTertiary,
        groupTitleFontSize: 12,
      },
      Table: {
        headerBg: subtleBg,
        headerColor: textSecondary,
        rowHoverBg: hoverBg,
        /** 拟物下取消表头分割线，改为整体凹陷（见 neumorphism.css） */
        borderColor: borderSecondary,
      },
      Button: {
        primaryShadow: isNeu
          ? isDark
            ? '6px 6px 14px rgba(0,0,0,0.45), -6px -6px 14px rgba(255,255,255,0.07)'
            : '6px 6px 14px rgba(11,74,83,0.19), -6px -6px 14px rgba(255,255,255,0.76)'
          : `0 2px 6px ${isDark ? 'rgba(47,179,192,0.28)' : 'rgba(14,127,138,.2)'}`,
        defaultShadow: 'none',
        borderColorDisabled: 'transparent',
      },
      Card: {
        paddingLG: 20,
        borderRadiusLG: radiusLG,
        headerBg: subtleBg,
        colorBorderSecondary: borderSecondary,
      },
      Form: {
        itemMarginBottom: 16,
        verticalLabelPadding: '0 0 4px',
      },
      Typography: {
        titleMarginTop: 0,
      },
      Modal: {
        contentBg: isDark ? '#2C353B' : isNeu ? '#E8EBF2' : '#FFFFFF',
        headerBg: 'transparent',
      },
      Drawer: {
        colorBgElevated: isDark ? '#2C353B' : isNeu ? '#E8EBF2' : '#FFFFFF',
      },
      Input: {
        colorBgContainer: isNeu ? containerBg : isDark ? '#1F2529' : '#FFFFFF',
        activeShadow: 'none',
        activeBorderColor: primary,
        hoverBorderColor: isNeu ? 'transparent' : primaryBorder,
      },
      Select: {
        colorBgContainer: isNeu ? containerBg : isDark ? '#1F2529' : '#FFFFFF',
        optionSelectedBg: primaryBg,
      },
      Pagination: {
        itemActiveBg: primaryBg,
      },
      Tabs: {
        itemSelectedColor: primary,
        inkBarColor: primary,
      },
    },
  };
}

export default getAntdTheme;
