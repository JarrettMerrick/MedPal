import { useSearchParams } from 'react-router-dom';
import { useCallback, useMemo } from 'react';

/**
 * 列表页分页/搜索/筛选状态持久化到 URL search params，
 * 确保浏览器后退/前进时恢复用户的分页位置和筛选条件。
 *
 * @param defaults - 默认值字典，key 为参数名，value 为默认字符串值
 * @returns params - 当前参数值（含默认值回填）
 * @returns setParam - 更新单个参数（使用 replace 避免产生多余历史记录）
 * @returns setParams - 批量更新参数
 */
export function usePageParams(defaults: Record<string, string>) {
  const [searchParams, setSearchParams] = useSearchParams();

  // 从 URL 读取，缺失时回退到默认值
  const params = useMemo(() => {
    const result: Record<string, string> = {};
    for (const key of Object.keys(defaults)) {
      result[key] = searchParams.get(key) || defaults[key];
    }
    return result;
  }, [searchParams, defaults]);

  // 更新单个参数（保留其他参数不变），replace 避免污染历史记录
  const setParam = useCallback(
    (key: string, value: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (value && value !== defaults[key]) {
          next.set(key, value);
        } else {
          next.delete(key); // 值与默认相同则不写入 URL，保持 URL 简洁
        }
        return next;
      }, { replace: true });
    },
    [setSearchParams, defaults],
  );

  // 批量更新参数
  const setParams = useCallback(
    (updates: Record<string, string>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (value && value !== defaults[key]) {
            next.set(key, value);
          } else {
            next.delete(key);
          }
        }
        return next;
      }, { replace: true });
    },
    [setSearchParams, defaults],
  );

  return { params, setParam, setParams };
}