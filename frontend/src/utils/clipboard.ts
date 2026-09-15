// [新增 2026-09-14] 剪贴板复制工具

/**
 * 复制文本到剪贴板。
 *
 * 为什么需要回退方案：
 *   异步 Clipboard API（navigator.clipboard）**仅在安全上下文**（HTTPS 或 localhost）可用。
 *   本系统按设计多部署在院内网并以 http 访问，此时 navigator.clipboard 为 undefined，
 *   直接调用会抛错导致「复制」功能在真实环境中完全失效。
 *   因此这里优先用 Clipboard API，不可用时回退到经典的 textarea + execCommand('copy')。
 *
 * @returns 是否复制成功（失败由调用方决定如何提示，本函数不抛异常）
 */
export async function copyText(text: string): Promise<boolean> {
  const value = text ?? '';
  if (!value) return false;

  // 方案一：异步 Clipboard API（需安全上下文）
  if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // 用户拒绝授权或浏览器异常时，继续尝试回退方案
    }
  }

  // 方案二：临时 textarea + execCommand 回退（兼容 http 访问的旧环境）
  try {
    const ta = document.createElement('textarea');
    ta.value = value;
    // 只读 + 移出视口：避免触发移动端键盘弹出与页面滚动
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    ta.style.left = '-1000px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, value.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
