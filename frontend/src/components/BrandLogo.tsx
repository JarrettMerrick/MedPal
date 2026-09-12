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
 * 用法：
 *   <BrandLogo height={34} />                       // 导航栏
 *   <div style={{ height: 64, width: 'fit-content', padding: '0 16px', ... }}>
 *     <BrandLogo height={40} />                     // 外层「显示框」高度固定、宽度自适应
 *   </div>
 *
 * 说明：
 * - 未上传自定义 Logo 时自动回退内置默认图，尺寸口径完全一致；
 * - 默认 `maxWidth: '100%'`，容器过窄时按比例缩小（objectFit: contain 不变形）。
 */
import React from 'react';

import DefaultLogo from '../icon/MedPal_Logo.png';
import { useBranding } from '../contexts/BrandingContext';

interface BrandLogoProps {
  /** 固定显示高度（px）。宽度按 Logo 原始宽高比自动计算 */
  height: number;
  /** 附加样式（可覆盖 maxWidth / flexShrink 等） */
  style?: React.CSSProperties;
  className?: string;
  alt?: string;
}

const BrandLogo: React.FC<BrandLogoProps> = ({ height, style, className, alt = '单位 Logo' }) => {
  const { logoUrl } = useBranding();
  return (
    <img
      src={logoUrl || DefaultLogo}
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
