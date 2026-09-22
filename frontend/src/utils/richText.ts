// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE for details.

import DOMPurify from 'dompurify';
import { getFileToken } from './tokenStore';

/**
 * 富文本安全清洗（供 dangerouslySetInnerHTML 渲染与源码模式入库前过滤）。
 *
 * [修复] 为 /uploads/ 开头的 <img> 自动追加文件访问令牌（ftoken）：
 * 后端静态文件挂载受 S1 鉴权保护，富文本正文中的图片 URL 若不带 ftoken 会被拦截导致无法显示。
 *
 * [修复 2026-09-05] hook 改为通过 DOMPurify.addHook 注册：
 * ① 官方类型定义的 Config 不含 afterSanitizeAttributes 键，配置式传参触发 TS2769；
 * ② DOMPurify 运行时只执行 addHook 注册的 hook，原先配置式写法实际并不生效。
 *
 * [改造 2026-09-09] 由"默认白名单 + 增量放行"改为"显式白名单 + 危险内容过滤"：
 * - 只放行排版、表格、图片、链接等必要标签与 style/class 等属性；
 * - 过滤 script/iframe/embed/object 等危险标签与全部 on* 事件属性；
 * - 过滤 javascript:/expression(/vbscript:/behavior/@import 等危险样式；
 *   [放宽 2026-09-10] 放行常规 url()（http(s)/相对路径/data:image），仅拦截脚本协议；
 * - 禁用 data: 图片（图片统一走 /uploads/richtext 上传）。
 */

// 放行标签白名单：在原有排版标签基础上，补齐 HTML5 语义/结构标签，
// 使「完整 HTML 文档」（header/nav/main/footer、figure 等）粘贴后结构与布局完整保留。
const ALLOWED_TAGS = [
  'div', 'p', 'br', 'span', 'section', 'article',
  'header', 'footer', 'nav', 'main', 'aside',
  'figure', 'figcaption', 'address', 'details', 'summary',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'colgroup', 'col',
  'img', 'a',
  'strong', 'b', 'em', 'i', 'u', 's', 'del', 'ins', 'mark', 'small', 'sub', 'sup',
  'blockquote', 'hr', 'pre', 'code', 'kbd', 'samp', 'var', 'time', 'abbr',
  // [放宽 2026-09-10] 保守放行内联 SVG 图形子集（script/foreignObject/use/image/animate 等仍被禁止）
  'svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon',
  'text', 'tspan', 'defs', 'stop', 'title',
  'linearGradient', 'lineargradient', 'radialGradient', 'radialgradient',
];

// 放行属性白名单（style 支持内联 CSS，class 支持外部排版类，id 支持页内锚点）
const ALLOWED_ATTR = [
  'style', 'class', 'id', 'role', 'title', 'lang', 'dir',
  'src', 'alt', 'width', 'height', 'loading',
  'href', 'target', 'rel',
  'colspan', 'rowspan', 'span', 'align', 'valign',
  'border', 'cellpadding', 'cellspacing',
  // SVG 相关属性（大小写两种形态均列入，避免解析差异导致属性丢失）
  'viewBox', 'viewbox', 'xmlns', 'fill', 'fill-rule', 'clip-rule',
  'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
  'd', 'cx', 'cy', 'r', 'rx', 'ry', 'x', 'y', 'x1', 'y1', 'x2', 'y2',
  'points', 'transform', 'preserveAspectRatio', 'preserveaspectratio',
  'opacity', 'offset', 'stop-color', 'stop-opacity',
];

// 危险标签（白名单之外的兜底显式禁止）
const FORBID_TAGS = [
  'script', 'iframe', 'embed', 'object', 'link', 'style',
  'form', 'input', 'button', 'select', 'textarea', 'meta', 'base', 'math',
  // SVG 中可被滥用或引用外部的元素
  'foreignObject', 'foreignobject', 'use', 'image', 'animate', 'set',
  'animateMotion', 'animatemotion', 'animateTransform', 'animatetransform',
];

// 危险属性（全部事件属性；DOMPurify 默认已拦截 on*，此处显式声明便于审计）
const FORBID_ATTR = [
  'onclick', 'ondblclick', 'onerror', 'onload', 'onunload',
  'onmouseover', 'onmouseout', 'onmousedown', 'onmouseup', 'onmousemove',
  'onkeydown', 'onkeyup', 'onkeypress',
  'onfocus', 'onblur', 'onchange', 'onsubmit', 'onreset',
  'onabort', 'ondrag', 'ondrop', 'oncopy', 'onpaste', 'oncut',
  'srcdoc', 'formaction', 'xlink:href',
];

// 危险 CSS：脚本协议 / 表达式 / 旧版行为 / @import（保留拦截）
const DANGEROUS_CSS_RE = /(javascript\s*:|vbscript\s*:|expression\s*\(|behavior\s*:|-moz-binding|@import)/gi;

// url(...) 内嵌危险协议：仅拦截 javascript:/vbscript:/data:text/html；
// 放行常规 http(s)、相对路径与 data:image 背景图（[放宽 2026-09-10]）
const DANGEROUS_CSS_URL_RE = /url\s*\(\s*['"]?\s*(?:javascript|vbscript|data\s*:\s*text\/html)[^)]*\)/gi;

// 仅允许 http(s)/mailto/tel 与相对地址（禁用 data: 与 javascript: 等协议）
const ALLOWED_URI_REGEXP = /^(?:(?:https?|mailto|tel):|\/|#|\.\/|\.\.\/|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i;

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.nodeType !== 1) return; // 仅处理元素节点
  const el = node as Element;

  // ① 图片：禁用 data: 内联图（统一走服务器上传），并为 /uploads/ 图片追加 ftoken
  if (el.tagName === 'IMG') {
    const src = el.getAttribute('src') || '';
    if (src.trim().toLowerCase().startsWith('data:')) {
      el.removeAttribute('src');
    } else if (src.startsWith('/uploads/')) {
      const ftoken = getFileToken();
      if (ftoken) {
        const sep = src.includes('?') ? '&' : '?';
        el.setAttribute('src', `${src}${sep}ftoken=${encodeURIComponent(ftoken)}`);
      }
    }
  }

  // ② 链接：外链统一加 rel=noopener noreferrer，防止 tabnabbing
  if (el.tagName === 'A') {
    const href = el.getAttribute('href') || '';
    if (href.trim().toLowerCase().startsWith('javascript:')) {
      el.removeAttribute('href');
    } else if (el.getAttribute('target') === '_blank') {
      el.setAttribute('rel', 'noopener noreferrer');
    }
  }

  // ③ 内联样式：移除脚本协议/表达式等危险写法，保留颜色、边距、渐变、背景图等常规样式
  if (el.hasAttribute('style')) {
    const raw = el.getAttribute('style') || '';
    const cleaned = raw.replace(DANGEROUS_CSS_RE, '').replace(DANGEROUS_CSS_URL_RE, '');
    if (cleaned !== raw) {
      el.setAttribute('style', cleaned);
    }
  }
});

/** 匹配 <style>...</style> 内联样式表（含属性写法） */
const STYLE_BLOCK_RE = /<style[^>]*>([\s\S]*?)<\/style>/gi;

/**
 * [新增 2026-09-09] 提取 HTML 中所有 <style> 样式表内容（已移除危险写法）。
 * 用于支持粘贴完整 HTML 文档（带 class 样式），在渲染时再按容器作用域注入。
 */
export function extractStyleBlocks(html: string): string[] {
  const blocks: string[] = [];
  (html || '').replace(STYLE_BLOCK_RE, (_m, css: string) => {
    blocks.push(String(css || ''));
    return '';
  });
  return blocks.map((css) =>
    css
      .replace(DANGEROUS_CSS_RE, '')
      .replace(DANGEROUS_CSS_URL_RE, '')
      .replace(/\/\*[\s\S]*?\*\//g, ''),
  );
}

/**
 * 按「顶层逗号」切分选择器列表。
 * 忽略括号 ()、方括号 [] 与引号内的逗号（如 :is(a,b)、[data-x="a,b"]），
 * 避免把 linear-gradient(...) 之类的参数误当选择器分隔符。
 */
function splitSelectorList(selector: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote = '';
  let cur = '';
  for (let i = 0; i < selector.length; i++) {
    const ch = selector[i];
    if (quote) {
      cur += ch;
      if (ch === quote && selector[i - 1] !== '\\') quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1);
    if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; continue; }
    cur += ch;
  }
  parts.push(cur);
  return parts.map((p) => p.trim()).filter(Boolean);
}

/** 为单个选择器组加上容器前缀，避免样式外溢到整个系统 */
function prefixSelector(selectorGroup: string, scope: string): string {
  return splitSelectorList(selectorGroup)
    .map((raw) => {
      const sel = raw.trim();
      if (!sel) return '';
      // html / body / :root → 容器本身（如 :root{--brand:...} 的变量可在容器内继承）
      if (/^(html|body|:root)$/i.test(sel)) return scope;
      // 通配符 → 容器及其后代（如 *{box-sizing:border-box}）
      if (sel === '*') return `${scope}, ${scope} *`;
      return `${scope} ${sel}`;
    })
    .filter(Boolean)
    .join(', ');
}

/** 找到与 openIdx 处 '{' 配对的 '}' 下标（忽略引号内的花括号） */
function findMatchingBrace(css: string, openIdx: number): number {
  let depth = 0;
  let quote = '';
  for (let i = openIdx; i < css.length; i++) {
    const ch = css[i];
    if (quote) {
      if (ch === quote && css[i - 1] !== '\\') quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) return i; }
  }
  return css.length; // 未闭合时的兜底
}

/**
 * 内部不做选择器作用域化的 at-rule：
 * 其块内是「声明」或「关键帧步骤」，加了容器前缀会破坏语义。
 */
const NON_SCOPING_AT_RULES = new Set([
  'font-face', 'page', 'keyframes', '-webkit-keyframes', '-moz-keyframes',
  'counter-style', 'property', 'font-feature-values', 'viewport',
]);

/** 递归处理一段 CSS：普通规则加容器前缀，容器型 at-rule 递归下探 */
function scopeNodes(css: string, scope: string): string {
  let out = '';
  let i = 0;
  while (i < css.length) {
    const braceIdx = css.indexOf('{', i);
    const semiIdx = css.indexOf(';', i);
    // 无块 at-rule 语句（如 @charset "utf-8";）原样保留
    if (semiIdx !== -1 && (braceIdx === -1 || semiIdx < braceIdx)) {
      const stmt = css.slice(i, semiIdx + 1).trim();
      if (stmt.startsWith('@')) { out += stmt; i = semiIdx + 1; continue; }
    }
    if (braceIdx === -1) { out += css.slice(i); break; }

    const prelude = css.slice(i, braceIdx).trim();
    const endIdx = findMatchingBrace(css, braceIdx);
    const inner = css.slice(braceIdx + 1, endIdx);

    if (prelude.startsWith('@')) {
      const name = (prelude.slice(1).match(/^[-a-z]+/i) || [''])[0].toLowerCase();
      // @media/@supports/@layer/@container 等递归；@keyframes/@font-face 等原样保留
      out += NON_SCOPING_AT_RULES.has(name)
        ? `${prelude}{${inner}}`
        : `${prelude}{${scopeNodes(inner, scope)}}`;
    } else if (prelude) {
      out += `${prefixSelector(prelude, scope)}{${inner}}`;
    } else {
      out += `{${inner}}`;
    }
    i = endIdx + 1;
  }
  return out;
}

/**
 * [新增 2026-09-09 · 重写 2026-09-10] 将样式表限定到指定容器作用域内：
 * 把每条规则的选择器加上容器前缀（.container → .rich-text-content .container），
 * 支持 @media / @supports 等容器型 at-rule 递归处理，@keyframes / @font-face 原样保留，
 * 保证外部网页/Word 导出的完整 HTML 还原排版，且不污染系统全局样式。
 */
export function scopeCss(css: string, scope = '.rich-text-content'): string {
  return scopeNodes(css || '', scope);
}

/** [新增 2026-09-09] 取原始 HTML 的样式表并生成限定作用域、可直接注入的 CSS */
export function buildScopedStyleCss(html: string, scope = '.rich-text-content'): string {
  const blocks = extractStyleBlocks(html).filter((b) => b.trim());
  if (!blocks.length) return '';
  return scopeCss(blocks.join('\n'), scope);
}

export function sanitizeRichTextHtml(html: string): string {
  // [新增 2026-09-09] 先剥离 <style>：样式表改由 buildScopedStyleCss 限定作用域后注入，
  // 避免 body{}、*{} 等规则污染整个系统页面
  const withoutStyleBlocks = (html || '').replace(STYLE_BLOCK_RE, '');
  return DOMPurify.sanitize(withoutStyleBlocks, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    FORBID_TAGS,
    FORBID_ATTR,
    ALLOWED_URI_REGEXP,
    ALLOW_DATA_ATTR: false,
    // 保留合法的 HTML 实体与注释移除
    KEEP_CONTENT: true,
    RETURN_TRUSTED_TYPE: false,
  } as Parameters<typeof DOMPurify.sanitize>[1]);
}

/**
 * [新增 2026-09-09] 保留样式表的清洗（供编辑器粘贴/源码应用使用）：
 * 正文按白名单清洗，原始 <style> 块原样保留在内容中，
 * 渲染时再由 buildScopedStyleCss 统一限定作用域，保证样式不丢失。
 */
export function sanitizeRichTextHtmlKeepStyle(html: string): string {
  const clean = sanitizeRichTextHtml(html);
  const blocks = extractStyleBlocks(html).filter((b) => b.trim());
  if (!blocks.length) return clean;
  const styleTag = blocks.map((css) => `<style>${css}</style>`).join('');
  return clean + styleTag;
}
