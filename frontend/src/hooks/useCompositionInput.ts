import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * 处理中文输入法（IME）组合输入的 hook。
 * 
 * 问题背景：
 * 当使用拼音输入法输入中文时，onChange 会在每个拼音字母输入时触发（组合过程中间态）。
 * 如果在 onChange 里直接更新 URL 参数（通过 setParam），会导致 React 重新渲染、
 * 输入框 value 被重置，IME 组合被中断，每次中断都把当前的拼音字母"固化"到值里。
 * 
 * 解决方案：
 * 通过 onCompositionStart/onCompositionEnd 追踪 IME 状态，
 * 组合过程中不更新 URL，组合结束时才写入。
 * 
 * @param externalValue - 来自外部（URL params）的值
 * @param onCommit - 组合结束后的回调（接收最终值）
 */
export function useCompositionInput(
  externalValue: string,
  onCommit: (value: string) => void
) {
  const [value, setValue] = useState(externalValue);
  const isComposing = useRef(false);

  // 外部值变化时同步（如 allowClear 触发 URL 清空、手动 setParam 等）
  useEffect(() => {
    if (!isComposing.current) {
      setValue(externalValue);
    }
  }, [externalValue]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newValue = e.target.value;
      setValue(newValue);
      
      if (!isComposing.current) {
        onCommit(newValue);
      }
    },
    [onCommit]
  );

  const handleCompositionStart = useCallback(() => {
    isComposing.current = true;
  }, []);

  const handleCompositionEnd = useCallback(
    (e: React.CompositionEvent<HTMLInputElement>) => {
      isComposing.current = false;
      const finalValue = e.currentTarget.value;
      setValue(finalValue);
      onCommit(finalValue);
    },
    [onCommit]
  );

  return {
    value,
    handleChange,
    handleCompositionStart,
    handleCompositionEnd,
  };
}
