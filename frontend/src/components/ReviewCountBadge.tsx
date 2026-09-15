// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 红底白字计数角标（通用）。
 *
 * [新增 2026-09-15] 最初为「信息审核」菜单待审数量设计（页内两个 Tab 同步使用）；
 * [调整 2026-09-15] 现同时服务于「站内信」菜单的未读数量（unread），
 * 两处角标共用同一组件与同一配色，避免各写一份样式后逐渐走形。
 *
 * 约定：
 * - 数量为 0 时不渲染（没有待办就不打扰），有 children 时原样透传（如包裹菜单图标）；
 * - 超过 99 显示「99+」，避免三位数把菜单/Tab 文本挤变形；
 * - 底色/文字色写死为红底白字，不随主题 token 漂移（两处口径完全一致）；
 * - 传 children 时改用包裹模式（角标吸附在子元素右上角），供折叠态菜单挂图标使用。
 */
import React from 'react';
import { Badge } from 'antd';

/** 红底白字（需求指定配色） */
const BADGE_STYLE: React.CSSProperties = {
  backgroundColor: '#FF4D4F',
  color: '#FFFFFF',
  boxShadow: 'none',
};

interface ReviewCountBadgeProps {
  /** 计数（<=0 不渲染角标）：信息审核待审数 / 站内信未读数 */
  count: number;
  /** 角标相对定位微调（菜单内联展示时用于贴合行高） */
  offset?: [number, number];
  /** 尺寸：菜单项用 small 更贴合行高，Tab 用默认更醒目 */
  size?: 'small' | 'default';
  /** 可选子元素：传入则角标吸附在其右上角（折叠态菜单包图标） */
  children?: React.ReactNode;
}

const ReviewCountBadge: React.FC<ReviewCountBadgeProps> = ({
  count, offset, size = 'default', children,
}) => {
  // 无待办：不额外套一层 Badge 外壳，直接透传子元素（无子元素即不渲染任何内容）
  if (count <= 0) return <>{children}</>;
  return (
    <Badge
      count={count}
      overflowCount={99}
      showZero={false}
      size={size}
      offset={offset}
      style={BADGE_STYLE}
    >
      {children}
    </Badge>
  );
};

export default ReviewCountBadge;
