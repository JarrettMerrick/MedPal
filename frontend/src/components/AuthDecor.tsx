// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 认证页（登录 / 注册）品牌面板的装饰层 —— 新拟态（Soft UI）版本。
 *
 * [改版 2026-09-17 · 第 3 版] 由「SVG 线性描边图形」改为「DOM 形状 + 双向阴影」：
 * 新拟态的空间感来自阴影而非线条，若沿用描边图形会与控件的材质语言冲突，
 * 因此装饰元素与表单控件使用同一套「凸起 / 凹陷」规则：
 *
 *   - 凸起圆盘（左上）  ：大面积浮起，打破面板的平整感；
 *   - 凹陷点阵（右上）  ：细密圆点被"刻"进面板，提供细腻质感；
 *   - 凸起十字（右中）  ：医疗符号的新拟态表达（品牌色双臂 + 缓慢浮动）；
 *   - 凹陷圆  （左下）  ：与左上圆盘形成对角呼应；
 *   - 凸起胶囊（右下）  ：高低错落，类比数据条 / 脉搏，中间一枚用品牌色点缀。
 *
 * 交互与可访问性：
 * - 整层 `aria-hidden`；`pointer-events: none`，不拦截表单交互；
 * - 装饰样式（尺寸、阴影、媒体查询下的显隐）全部在 global.css 的
 *   `.auth-decor__*` 中定义，本组件只负责结构，便于统一调参；
 * - 十字的浮动动画在 `prefers-reduced-motion` 下自动关闭。
 */
import React from 'react';

const AuthDecor: React.FC = () => (
  <div className="auth-decor" aria-hidden="true">
    {/* 凸起圆盘（左上） */}
    <span className="auth-decor__disc" />

    {/* 凹陷点阵（右上） */}
    <span className="auth-decor__dots" />

    {/* 凸起医疗十字（右中，缓慢浮动） */}
    <span className="auth-decor__cross" />

    {/* 凹陷圆（左下） */}
    <span className="auth-decor__concave" />

    {/* 凸起胶囊组（右下） */}
    <span className="auth-decor__pills">
      <span className="auth-decor__pill auth-decor__pill--1" />
      <span className="auth-decor__pill auth-decor__pill--2" />
      <span className="auth-decor__pill auth-decor__pill--3" />
    </span>
  </div>
);

export default AuthDecor;
