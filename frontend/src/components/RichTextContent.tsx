// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE for details.

/**
 * [新增 2026-09-09] 富文本内容统一渲染容器
 * ------------------------------------------------------------
 * 目的：保证「编辑器预览」与「发布后展示（通知公告 / 制度牌）」渲染结果完全一致。
 * 做法：所有富文本展示都经过本组件 → 同一套清洗（utils/richText）+ 同一套容器 CSS 约束。
 *
 * 容器约束（按需求）：
 * - 容器与其内部所有元素 max-width:100%、box-sizing:border-box、word-break:break-word
 * - 图片 max-width:100% 且高度自适应；表格自适应宽度；代码块自动换行
 * - 整体不出现横向滚动条，长内容不截断
 */
import React, { useMemo } from 'react';
import { sanitizeRichTextHtml, buildScopedStyleCss } from '../utils/richText';

const CONTENT_CSS = `
/* [调整 2026-09-10] 统一用 :where() 包裹，使默认样式优先级为 0：
   当粘贴的完整 HTML 自带 <style> 排版时，作者样式可正常覆盖这里的默认值，
   未自带样式的普通富文本仍沿用下列兜底样式。 */
:where(.rich-text-content) {
  width: 100%;
  box-sizing: border-box;
  overflow-x: hidden;
  word-break: break-word;
}
:where(.rich-text-content, .rich-text-content *) {
  max-width: 100%;
  box-sizing: border-box;
  word-break: break-word;
  overflow-wrap: break-word;
}
:where(.rich-text-content) img {
  max-width: 100% !important;
  height: auto !important;
  display: block;
  margin: 8px 0;
}
:where(.rich-text-content) table {
  width: 100% !important;
  max-width: 100% !important;
  border-collapse: collapse;
  margin: 12px 0;
}
:where(.rich-text-content) table td, :where(.rich-text-content) table th {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  word-break: break-word;
}
:where(.rich-text-content) table th { background-color: #f9fafb; font-weight: 500; }
:where(.rich-text-content) p { margin: 8px 0; }
:where(.rich-text-content) h1, :where(.rich-text-content) h2, :where(.rich-text-content) h3,
:where(.rich-text-content) h4, :where(.rich-text-content) h5, :where(.rich-text-content) h6 {
  margin: 16px 0 8px;
  font-weight: 600;
}
:where(.rich-text-content) ul, :where(.rich-text-content) ol { margin: 8px 0; padding-left: 24px; }
:where(.rich-text-content) a { color: #1565B8; }
:where(.rich-text-content) pre, :where(.rich-text-content) code {
  white-space: pre-wrap !important;
  word-break: break-word;
  overflow-x: hidden;
}
`;

// 样式只注入一次（多处渲染时避免重复 <style>）
let styleInjected = false;
function ensureStyleInjected() {
  if (styleInjected || typeof document === 'undefined') return;
  styleInjected = true;
  const el = document.createElement('style');
  el.setAttribute('data-rich-text-content', 'true');
  el.textContent = CONTENT_CSS;
  document.head.appendChild(el);
}

interface RichTextContentProps {
  /** 原始富文本 HTML（本组件内部统一清洗） */
  html: string;
  /** 附加类名（如制度详情的 regulation-content，兼容既有样式） */
  className?: string;
  style?: React.CSSProperties;
}

const RichTextContent: React.FC<RichTextContentProps> = ({ html, className = '', style }) => {
  ensureStyleInjected();
  /**
   * [新增 2026-09-09] 支持完整 HTML 文档中的 <style> 样式表：
   * 样式选择器统一限定到 .rich-text-content 容器内（body/html/* → 容器本身），
   * 既还原 class 排版（如 .container、.rule-list），又不会影响系统其他页面。
   */
  const scopedCss = useMemo(() => buildScopedStyleCss(html), [html]);
  const innerHtml = (scopedCss ? `<style>${scopedCss}</style>` : '') + sanitizeRichTextHtml(html || '');

  return (
    <div
      className={`rich-text-content ${className}`.trim()}
      style={style}
      dangerouslySetInnerHTML={{ __html: innerHtml }}
    />
  );
};

export default RichTextContent;
