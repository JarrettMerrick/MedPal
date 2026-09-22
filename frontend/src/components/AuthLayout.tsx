// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 公开认证页（登录 / 注册）的统一布局 —— 新拟态（Neumorphism / Soft UI）风格。
 *
 * [改版 2026-09-17 · 第 3 版] 由「渐变分栏」切换为新拟态：
 * 整页使用**单一底色**（品牌青蓝同色系浅调 #e7eef1），所有元素不画边框，
 * 仅靠**双向柔和阴影**表达空间关系 —— 面板/按钮凸起，输入框/提示条凹陷。
 *
 *   桌面（≥992px）        ┌──────────────────────┬───────────────────┐
 *                        │ 品牌面板（凸起大圆角） │  表单区（底色直铺）  │
 *                        │ 装饰：圆盘/点阵/十字/胶囊│  标题+表单+注册入口  │
 *                        │ Logo 板 + 单位/系统名   │  输入框凹陷、按钮凸起 │
 *                        └──────────────────────┬───────────────────┘
 *   窄屏（<992px）        顶部品牌面板（横向压缩，装饰简化）
 *                        ─────────────────────────────────────
 *                        表单区（底色直铺）
 *
 * 设计要点：
 * - **左侧承载品牌与装饰**：新拟态装饰层（DOM + 阴影，见 AuthDecor），
 *   空白由「凸起 / 凹陷的形状」填充，与表单形成统一的材质语言；
 * - **右侧只做一件事**：表单直接铺在底色上，不再套任何容器，
 *   立体感全部由控件自身（凹陷输入框 / 凸起按钮）提供；
 * - **两页共用**：登录与注册共用本布局，从登录跳注册时左侧品牌面板不变化；
 * - **断点与 antd 对齐**：使用 lg（992px）作为折叠阈值，CSS 与 useBreakpoint 一致。
 */
import React from 'react';
import { Grid } from 'antd';

import { useBranding } from '../contexts/BrandingContext';
import BrandLogo from './BrandLogo';
import AuthDecor from './AuthDecor';

const { useBreakpoint } = Grid;

interface AuthLayoutProps {
  children: React.ReactNode;
  /** 表单区内容最大宽度（px）：登录 400，注册表单较宽用 440 */
  formWidth?: number;
}

const AuthLayout: React.FC<AuthLayoutProps> = ({ children, formWidth = 400 }) => {
  const branding = useBranding();
  const screens = useBreakpoint();
  // 窄屏（<992px，与 global.css 折叠断点一致）：品牌面板转为顶部面板，Logo 等比缩小
  const isNarrow = !screens.lg;

  return (
    <div className="auth-neu">
      <div className="auth-neu__inner">
        {/* ── 左：品牌面板（新拟态凸起） ── */}
        <aside className="auth-neu__brand">
          <AuthDecor />
          <div className="auth-neu__brand-inner">
            <div className="auth-neu__logo">
              <BrandLogo height={isNarrow ? 32 : 40} />
            </div>
            <h1 className="auth-neu__org">{branding.orgNameCn}</h1>
            <p className="auth-neu__system">{branding.systemName}</p>
            {branding.orgNameEn && <p className="auth-neu__org-en">{branding.orgNameEn}</p>}
            {/* 宣传标语（未配置时不渲染）；窄屏隐藏，避免顶部面板过高 */}
            {branding.slogan && (
              <div className="auth-neu__slogan">
                <span className="auth-neu__slogan-line" />
                <span>{branding.slogan}</span>
              </div>
            )}
          </div>
        </aside>

        {/* ── 右：表单区（底色直铺，登录 / 注册内容在此渲染） ── */}
        <main className="auth-neu__main">
          <div className="auth-neu__form" style={{ maxWidth: formWidth }}>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};

export default AuthLayout;
