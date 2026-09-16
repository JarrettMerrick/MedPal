// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 统一品牌 Logo 展示组件：**显示高度固定，宽度按 Logo 原始宽高比等比伸缩**。
 *
 * 背景：[调整 2026-09-10] 此前各页面用「固定宽高的正方形框 + maxWidth/maxHeight」
 * 约束 Logo，横向 Logo（如长条形院徽）会被塞进正方形后等比缩小，
 * 视觉上又小又空、留白严重。
 * 现统一为：高度由调用方指定并保持不变，宽度按上传图片的原始比例自适应，
 * 长条形 Logo 也能完整、清晰地铺满可用宽度。
 *
 * [调整 2026-09-16] **移除内置位图默认 Logo**（原 src/icon/MedPal_Logo.png）：
 *   位图资源不可审计，历史上还被替换成过非本项目机构的标识，存在品牌残留风险；
 *   现改为**代码绘制**的默认样式（内联 SVG 医疗十字徽标，取系统主色），
 *   无任何外部图片依赖、任意尺寸清晰、且不可能夹带第三方标识。
 *   单位如需自有 Logo，请在「系统设置 → 单位设置」上传，上传后自动替换该默认样式。
 *
 * 用法：
 *   <BrandLogo height={34} />                       // 导航栏
 *   <div style={{ height: 64, width: 'fit-content', padding: '0 16px', ... }}>
 *     <BrandLogo height={40} />                     // 外层「显示框」高度固定、宽度自适应
 *   </div>
 *
 * 说明：
 * - 未上传自定义 Logo 时自动回退到内置默认样式（代码绘制），尺寸口径完全一致；
 * - 默认 `maxWidth: '100%'`，容器过窄时按比例缩小（objectFit: contain 不变形）。
 */
import React from 'react';

import { useBranding } from '../contexts/BrandingContext';
import { BRAND } from '../theme/tokens';

interface BrandLogoProps {
  /** 固定显示高度（px）。宽度按 Logo 原始宽高比自动计算 */
  height: number;
  /** 附加样式（可覆盖 maxWidth / flexShrink 等） */
  style?: React.CSSProperties;
  className?: string;
  alt?: string;
}

/**
 * 内置默认 Logo：**代码绘制**（系统主色圆角方块 + 白色医疗十字），正方形比例。
 * 不含任何外部图片文件，也不含任何机构标识文字，避免品牌残留。
 */
const DefaultLogo: React.FC<Required<Pick<BrandLogoProps, 'height'>> & Omit<BrandLogoProps, 'height'>> = ({
  height,
  style,
  className,
  alt = '单位 Logo',
}) => (
  <svg
    viewBox="0 0 32 32"
    width={height}
    height={height}
    className={className}
    role="img"
    aria-label={alt}
    style={{ display: 'block', flexShrink: 0, ...style }}
  >
    <rect width="32" height="32" rx="9" fill={BRAND.primary} />
    <path d="M14 6.6h4v7.4h7.4v4H18v7.4h-4V18H6.6v-4H14z" fill="#FFFFFF" />
  </svg>
);

const BrandLogo: React.FC<BrandLogoProps> = ({ height, style, className, alt = '单位 Logo' }) => {
  const { logoUrl } = useBranding();

  // 未配置自定义 Logo → 使用代码绘制的默认样式（不再依赖内置位图）
  if (!logoUrl) {
    return <DefaultLogo height={height} style={style} className={className} alt={alt} />;
  }

  return (
    <img
      src={logoUrl}
      alt={alt}
      className={className}
      style={{
        height,
        width: 'auto',
        maxWidth: '100%',
        objectFit: 'contain',
        display: 'block',
        ...style,
      }}
    />
  );
};

export default BrandLogo;
