/**
 * 专业能力段落解析工具
 *
 * [业务背景说明]
 * - 职责：将「专业擅长 / 社会任职 / 获得荣誉」三个字段的文本内容，解析为结构化段落数组，
 *   供详情页清晰分段渲染（段落标题、段落内容、排序序号）。
 * - 数据兼容：三个字段仍复用原数据库文本列（方案 A，不新增表）。文本支持两种写法：
 *   1) 纯文本或多段（以空行分隔为多个段落），无段落标题；
 *   2) 增强格式：以 `## ` 开头的行作为段落标题，其后内容为该段落正文（空行分隔段落）。
 * - 排序：按文本中出现顺序生成 sort_order（0,1,2...），前端按序渲染。
 */

export interface ExpertiseParagraph {
  /** 排序序号，从 0 递增 */
  sort_order: number;
  /** 段落标题，增强格式下存在，纯文本段落为 null */
  title: string | null;
  /** 段落内容（已 trim） */
  content: string;
}

/**
 * 解析单字段文本为段落数组。
 * @param text 数据库文本列内容（可能为 null / 空串 / 纯文本 / 增强格式）
 */
export function parseExpertiseParagraphs(text: string | null | undefined): ExpertiseParagraph[] {
  if (!text || !text.trim()) return [];

  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const paragraphs: ExpertiseParagraph[] = [];
  let currentTitle: string | null = null;
  let buffer: string[] = [];

  const flush = () => {
    const content = buffer.join('\n').trim();
    if (content) {
      paragraphs.push({ sort_order: paragraphs.length, title: currentTitle, content });
    }
    buffer = [];
    currentTitle = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    // 以 `## ` 开头的行视为段落标题
    const titleMatch = line.match(/^##\s+(.+)$/);
    if (titleMatch) {
      flush();
      currentTitle = titleMatch[1].trim();
      continue;
    }
    // 空行：分隔段落（仅当已有内容时刷新）
    if (line.trim() === '') {
      if (buffer.length > 0) flush();
      continue;
    }
    buffer.push(line);
  }
  flush();
  return paragraphs;
}
