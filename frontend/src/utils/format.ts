export function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// [修复 2026-09-02] P3: 统一 API 错误消息提取，避免到处使用 any 类型
import { AxiosError } from 'axios';

/**
 * 从 API 错误中提取用户友好的错误消息
 * 替代原来的 `(err as any)?.response?.data?.detail || '操作失败'` 模式
 */
export function getErrorMessage(error: unknown, fallback: string = '操作失败'): string {
  if (error instanceof AxiosError) {
    return error.response?.data?.detail || error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message || fallback;
  }
  if (typeof error === 'string') {
    return error || fallback;
  }
  return fallback;
}
