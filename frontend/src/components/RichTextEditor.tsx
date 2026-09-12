// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE for details.
// wangEditor - Copyright (c) 2021 - present wangEditor-team - MIT License

/**
 * [改造 2026-09-09] 富文本编辑器（wangEditor V5）
 *
 * 模式（切换控件在头部右侧）：可视化 / 源码 / 预览
 *
 * [重要修复] 完整 HTML（含 <style> 样式表、class 排版、div 布局）不再进入 wangEditor：
 * wangEditor 的模型不支持 div/class 等自定义结构，setHtml 后会被拍平成纯段落、class 丢失。
 * 因此：
 * - 检测到"自定义 HTML"时（含 <style>、class、div/section 等布局标签）→ 以「源码」为唯一编辑入口，
 *   可视化页签显示提示，避免结构被破坏；内容按白名单清洗后原样保存；
 * - 普通富文本（p/h1~h6/ul/ol/li/strong/表格/图片等）→ 正常在可视化模式编辑；
 * - 可视化模式粘贴到完整 HTML 文档时，自动转入源码模式保存，保证结构与样式不丢。
 *
 * 预览始终使用 RichTextContent（与发布后渲染完全一致，样式表按容器作用域注入）。
 */
import React, { useState, useEffect, useMemo, useRef } from 'react';
import '@wangeditor/editor/dist/css/style.css';
import { Editor, Toolbar } from '@wangeditor/editor-for-react';
import { IDomEditor, IEditorConfig, IToolbarConfig } from '@wangeditor/editor';
import { Segmented, Button, Alert } from 'antd';
import { CheckOutlined } from '@ant-design/icons';
import api from '../api/client';
import { sanitizeRichTextHtml, sanitizeRichTextHtmlKeepStyle } from '../utils/richText';
import RichTextContent from './RichTextContent';

interface RichTextEditorProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  className?: string;
}

type EditorMode = 'visual' | 'source' | 'preview';

/** 自定义（高级）HTML：含样式表、class 或 div/section 等布局标签，wangEditor 无法承载 */
const isAdvancedHtml = (html: string): boolean =>
  /<style[\s>]/i.test(html) ||
  /class\s*=\s*["']/i.test(html) ||
  /<(div|section|article|header|footer|nav|aside|figure)[\s>]/i.test(html);

const EDITOR_CSS = `
.rte-root { width: 100%; box-sizing: border-box; }
.rte-container {
  width: 100%; box-sizing: border-box; border: 1px solid #d9d9d9;
  border-radius: 8px; overflow: hidden; background: #fff;
}
.rte-header {
  display: flex; align-items: center; justify-content: flex-end;
  gap: 8px; flex-wrap: wrap; padding: 8px 10px;
  background: #fafafa; border-bottom: 1px solid #e8e8e8;
}
.rte-body { width: 100%; box-sizing: border-box; }
.rte-body .w-e-bar { flex-wrap: wrap; }
.rte-body .w-e-bar-item-group { flex-wrap: wrap; }
.rte-body .w-e-scroll { overflow-x: hidden !important; }
.rte-body .w-e-text-container,
.rte-body .w-e-text-container * {
  max-width: 100%; box-sizing: border-box; word-break: break-word; overflow-wrap: break-word;
}
.rte-body .w-e-text-container img { max-width: 100% !important; height: auto !important; }
.rte-body .w-e-text-container table { width: 100% !important; table-layout: fixed; }
.rte-source {
  display: block; width: 100%; box-sizing: border-box; min-height: 360px;
  padding: 12px 14px; border: 0; outline: none; resize: vertical;
  font-family: Consolas, Monaco, 'Courier New', monospace; font-size: 13px; line-height: 1.7;
  white-space: pre-wrap; word-break: break-word; overflow-x: hidden; color: #1F2933;
}
.rte-preview {
  width: 100%; box-sizing: border-box; padding: 12px 14px;
  min-height: 200px; max-height: 520px; overflow-y: auto; overflow-x: hidden;
}
.rte-notice { padding: 16px; }
@media (max-width: 768px) {
  .rte-header { justify-content: flex-start; }
  .rte-source { min-height: 260px; font-size: 12px; }
}
`;

const isImageFile = (file: File): boolean => file.type.startsWith('image/');

/** [修复] 图片上传服务器获取 URL，避免 base64 内嵌导致内容体积暴涨 */
const uploadImage = async (file: File): Promise<string | null> => {
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await api.post('/uploads/richtext', formData);
    return res.data?.url || null;
  } catch {
    return null;
  }
};

const RichTextEditor: React.FC<RichTextEditorProps> = ({
  value,
  onChange,
  placeholder = '请输入内容...',
  className = '',
}) => {
  const [editor, setEditor] = useState<IDomEditor | null>(null);
  /** 当前内容（完整 HTML，可能含 <style> 与 class） */
  const [html, setHtml] = useState<string>(value ?? '');
  /** 是否为自定义（高级）HTML：是则只能源码编辑 */
  const [advanced, setAdvanced] = useState<boolean>(() => isAdvancedHtml(value ?? ''));
  const [mode, setMode] = useState<EditorMode>(() => (isAdvancedHtml(value ?? '') ? 'source' : 'visual'));
  const [sourceText, setSourceText] = useState<string>(value ?? '');
  const [compact, setCompact] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches,
  );

  /**
   * [修复 2026-09-09] 编辑器改为完全非受控（不向 <Editor> 传 value）：
   * 传 value 时 editor-for-react 会在 value 变化后执行 setHtml 并触发 onChange，
   * 高级内容被传入 '' 导致内容被清空。现只在必要时手动 setHtml，并用 suppressRef 抑制回写。
   */
  const suppressRef = useRef(false);

  /** 提交内容：回调给表单 */
  const commit = (next: string, nextAdvanced: boolean) => {
    setHtml(next);
    setAdvanced(nextAdvanced);
    onChange?.(next);
  };

  /** 把内容写入编辑器（程序化写入，期间忽略 onChange 回写） */
  const loadIntoEditor = (content: string) => {
    if (!editor) return;
    suppressRef.current = true;
    editor.setHtml(content || '');
    window.setTimeout(() => { suppressRef.current = false; }, 0);
  };

  /** 编辑器创建完成：仅普通富文本载入内容，自定义 HTML 不载入 */
  const handleCreated = (ed: IDomEditor) => {
    setEditor(ed);
    if (advanced) return;
    suppressRef.current = true;
    ed.setHtml(sanitizeRichTextHtml(html) || '');
    window.setTimeout(() => { suppressRef.current = false; }, 0);
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(max-width: 768px)');
    const handler = (e: MediaQueryListEvent) => setCompact(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  // 同步外部 value（如表单回填/重置）
  useEffect(() => {
    if (value === undefined || value === html) return;
    const adv = isAdvancedHtml(value);
    setHtml(value);
    setAdvanced(adv);
    setSourceText(value);
    // 仅普通富文本才写入编辑器，避免自定义结构被拍平
    if (!adv) loadIntoEditor(sanitizeRichTextHtml(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    return () => {
      if (editor == null) return;
      editor.destroy();
      setEditor(null);
    };
  }, [editor]);

  /** 可视化模式编辑：编辑器内容即最终内容；高级内容与程序化写入期间不回写 */
  const handleChange = (ed: IDomEditor) => {
    if (advanced || suppressRef.current) return;
    commit(ed.getHtml(), false);
  };

  /** 应用源码：清洗后保存；自定义结构不进编辑器，普通富文本同步到编辑器 */
  const applySource = () => {
    const adv = isAdvancedHtml(sourceText);
    const cleaned = adv ? sanitizeRichTextHtmlKeepStyle(sourceText) : sanitizeRichTextHtml(sourceText);
    commit(cleaned, adv);
    setSourceText(cleaned);
    // 仅普通富文本写入编辑器；自定义 HTML 保持原样，编辑器不参与
    if (!adv) loadIntoEditor(cleaned);
  };

  const handleModeChange = (next: EditorMode) => {
    if (next === mode) return;
    if (mode === 'source' && next !== 'source') applySource();
    if (next === 'source') setSourceText(html);
    if (next === 'visual' && !advanced) loadIntoEditor(sanitizeRichTextHtml(html));
    setMode(next);
  };

  /** 用户确认在可视化模式编辑自定义 HTML（会丢失 class/布局结构） */
  const forceVisualEdit = () => {
    const simple = sanitizeRichTextHtml(html);
    setAdvanced(false);
    commit(simple, false);
    loadIntoEditor(simple);
  };

  const toolbarConfig: Partial<IToolbarConfig> = {};

  const editorConfig: Partial<IEditorConfig> = {
    placeholder,
    MENU_CONF: {
      uploadImage: {
        customUpload: async (file: File, insertFn: (url: string, alt?: string, href?: string) => void) => {
          if (!isImageFile(file)) return;
          const url = await uploadImage(file);
          if (url) insertFn(url);
        },
      },
    },
    customPaste: (ed: IDomEditor, event: ClipboardEvent) => {
      const clipboard = event.clipboardData;
      if (!clipboard) return true;
      const pastedHtml = clipboard.getData('text/html');
      const plainText = clipboard.getData('text/plain');
      if (pastedHtml) {
        if (isAdvancedHtml(pastedHtml)) {
          // 完整 HTML 文档：不进编辑器，转源码模式保存，避免结构被拍平
          const cleaned = sanitizeRichTextHtmlKeepStyle(pastedHtml);
          commit(cleaned, true);
          setSourceText(cleaned);
          setMode('source');
          return false;
        }
        ed.dangerouslyInsertHtml(sanitizeRichTextHtml(pastedHtml));
        return false;
      }
      if (plainText) {
        ed.insertText(plainText);
        return false;
      }
      return false;
    },
  };

  const showEditor = mode === 'visual' && !advanced;
  const previewHtml = useMemo(() => html, [html]);

  return (
    <div className={`rte-root ${className}`.trim()}>
      <style>{EDITOR_CSS}</style>
      <div className="rte-container">
        <div className="rte-header">
          {mode === 'source' && (
            <Button size="small" type="primary" icon={<CheckOutlined />} onClick={applySource}>
              应用源码
            </Button>
          )}
          <Segmented
            value={mode}
            onChange={(v) => handleModeChange(v as EditorMode)}
            options={[
              { label: '可视化', value: 'visual' },
              { label: '源码', value: 'source' },
              { label: '预览', value: 'preview' },
            ]}
          />
        </div>

        {/* 可视化：普通富文本正常编辑；自定义 HTML 显示提示，避免结构被破坏 */}
        {mode === 'visual' && advanced && (
          <div className="rte-notice">
            <Alert
              type="info"
              showIcon
              message="当前内容包含自定义 HTML（class 排版 / 样式表 / div 布局）"
              description="可视化编辑会丢失这些结构，请在「源码」模式中编辑。预览与发布效果不受影响。"
              action={
                <Button size="small" danger onClick={forceVisualEdit}>
                  仍要可视化编辑
                </Button>
              }
            />
          </div>
        )}

        <div className="rte-body" style={{ display: showEditor ? 'block' : 'none' }}>
          <Toolbar editor={editor} defaultConfig={toolbarConfig} mode="default" style={{ borderBottom: '1px solid #e8e8e8' }} />
          <Editor
            defaultConfig={editorConfig}
            onCreated={handleCreated}
            onChange={handleChange}
            mode="default"
            style={{ height: compact ? 300 : 420, overflowY: 'auto' }}
          />
        </div>

        {/* 源码：完整 HTML 的唯一编辑入口 */}
        {mode === 'source' && (
          <textarea
            className="rte-source"
            value={sourceText}
            onChange={(e) => setSourceText(e.target.value)}
            spellCheck={false}
            placeholder="可输入或粘贴完整 HTML（含 <style> 样式表与 class 排版）；点击「应用源码」自动安全过滤，结构与样式完整保留"
          />
        )}

        {mode === 'preview' && (
          <div className="rte-preview">
            {previewHtml ? (
              <RichTextContent html={previewHtml} />
            ) : (
              <span style={{ color: '#97A3B2' }}>暂无内容</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RichTextEditor;
