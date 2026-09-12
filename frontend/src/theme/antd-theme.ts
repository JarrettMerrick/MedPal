// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 本文件为 Ant Design 5.x 全局主题配置文件，通过 ConfigProvider 注入整个应用。
 *
 * 设计原则（v1.1.0 UI 精致化，2026-08-07）：
 * - 主色由 #0052D9（数码品牌蓝）调整为 #0E7F8A（医疗青蓝），
 *   符合医院「信任、洁净、安宁」的气质，且相比纯蓝更现代
 * - 浅色轻盈侧边栏（siderBg #FFFFFF）+ 浅青胶囊选中态，告别传统深蓝后台模板
 * - 暖灰页面底 #F6F8FA、细边框 + 柔和分层阴影，提升卡片精致感
 * - 组件级 token 覆盖解决 Ant Design 默认样式与项目需求的差异
 *
 * 数据流向：theme → ConfigProvider → 全应用生效
 */

import type { ThemeConfig } from 'antd';

/** @constant Ant Design 5.x 全局主题配置 */
const theme: ThemeConfig = {
  token: {
    // ========== 品牌主色（医疗青蓝体系） ==========
    /** 主色 - 医疗青蓝 */
    colorPrimary: '#0E7F8A',
    /** 主色悬浮态 */
    colorPrimaryHover: '#1B8E99',
    /** 主色按下态 */
    colorPrimaryActive: '#0A6771',
    /** 主色浅色背景（选中/标签底） */
    colorPrimaryBg: '#E3F4F6',
    /** 主色浅色背景悬浮 */
    colorPrimaryBgHover: '#D6EEF1',
    /** 主色浅色边框 */
    colorPrimaryBorder: '#9AD0D6',
    /** 链接颜色与主色一致 */
    colorLink: '#0E7F8A',

    // ========== 功能色 ==========
    /** 成功/健康 - 治愈绿 */
    colorSuccess: '#16A34A',
    /** 警示 - 温和橙 */
    colorWarning: '#F59E0B',
    /** 危险 - 克制的红 */
    colorError: '#EF4444',
    /** 信息 - 同主色 */
    colorInfo: '#0E7F8A',

    // ========== 中性色（暖灰底 + 层级文字） ==========
    /** 页面底色（暖灰，非纯白） */
    colorBgLayout: '#F6F8FA',
    /** 容器背景 */
    colorBgContainer: '#FFFFFF',
    /** 主要边框 */
    colorBorder: '#E3E8EE',
    /** 次级边框/分割线 */
    colorBorderSecondary: '#EDF0F3',
    /** 主文字（深蓝灰，非纯黑） */
    colorText: '#1F2D3D',
    /** 次级文字 */
    colorTextSecondary: '#5C6B7A',
    /** 弱文字 */
    colorTextTertiary: '#8A97A6',
    /** 占位/头像底 */
    colorFillQuaternary: '#F1F4F7',

    // ========== 字体 ==========
    /** 字体栈 - 中文字体优先 */
    fontFamily: `"PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif`,
    /** 基准字号 14px */
    fontSize: 14,

    // ========== 形状与阴影（精致感关键） ==========
    /** 默认控件圆角 */
    borderRadius: 8,
    /** 大容器（卡片/弹窗）圆角 */
    borderRadiusLG: 12,
    /** 小元素（Tag/按钮）圆角 */
    borderRadiusSM: 6,
    /** 柔和分层阴影（卡片） */
    boxShadow: '0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)',
    /** 弹窗等浮层阴影 */
    boxShadowSecondary: '0 12px 32px rgba(16,24,40,.10)',

    /** 内边距基准 */
    padding: 16,
    /** 外边距基准 */
    margin: 16,
  },

  components: {
    Layout: {
      /** 浅色侧边栏背景 */
      siderBg: '#FFFFFF',
      /** 顶栏白色背景 */
      headerBg: '#FFFFFF',
      /** 顶栏高度 56px */
      headerHeight: 56,
    },
    Menu: {
      /** 浅色菜单：透明底 */
      itemBg: 'transparent',
      /** 浅青胶囊选中背景 */
      itemSelectedBg: '#E3F4F6',
      /** 选中文字 - 医疗青蓝 */
      itemSelectedColor: '#0E7F8A',
      /** 悬浮背景 */
      itemHoverBg: '#F1F4F7',
      /** 菜单项圆角 */
      itemBorderRadius: 8,
      /** 菜单项高度（更舒展） */
      itemHeight: 44,
      /** 图标与文字间距 */
      iconMarginInlineEnd: 10,
      /** 子菜单背景透明（浅色） */
      subMenuItemBg: 'transparent',
      /** 分组标题颜色（弱化） */
      groupTitleColor: '#8A97A6',
      /** 分组标题字号 */
      groupTitleFontSize: 12,
    },
    Table: {
      /** 表头浅灰背景 */
      headerBg: '#F8FAFB',
      /** 表头文字 - 次级灰 */
      headerColor: '#5C6B7A',
      /** 行悬浮 - 浅青 */
      rowHoverBg: '#F0F8F9',
    },
    Button: {
      /** 主按钮柔和投影（医疗青蓝光晕） */
      primaryShadow: '0 2px 6px rgba(14,127,138,.2)',
    },
    Card: {
      /** 卡片内容区域内边距 */
      paddingLG: 20,
      /** 大容器圆角 12px */
      borderRadiusLG: 12,
      /** 卡片头部背景 */
      headerBg: '#F8FAFB',
    },
    Form: {
      /** 表单项底部间距 */
      itemMarginBottom: 16,
      /** 垂直布局标签内边距 */
      verticalLabelPadding: '0 0 4px',
    },
    // [修复 2026-09-05] antd v5 组件配置中不存在 Title 键（TS2353），
    // 标题间距由 Typography 组件 token 控制
    Typography: {
      /** 去除标题默认上间距，避免与容器 padding 叠加 */
      titleMarginTop: 0,
    },
  },
};

export default theme;
