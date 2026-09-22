// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 界面偏好上下文（外观风格 + 明暗模式）
 * ================================
 * 职责：
 *   1) 全站唯一的状态源：uiStyle（新拟物 / 经典）、colorMode（浅色 / 深色）；
 *   2) 持久化到 localStorage，刷新与重开浏览器后保持；
 *   3) 同步写入 <html> 的 data-ui-style / data-color-mode 属性，
 *      供 CSS 变量层（neu-tokens.css）与拟物覆盖层（neumorphism.css）消费；
 *   4) **首屏防闪烁**：在模块加载阶段（早于 React 渲染）就把已保存的偏好写入属性，
 *      避免出现「先经典后拟物」的闪动。
 *
 * 为什么用 <html> 属性而不是 class：
 *   - 属性选择器可以组合（[data-ui-style="neu"][data-color-mode="dark"]），
 *     优先级稳定、不依赖样式书写顺序，避免单属性同优先级的覆盖歧义；
 *   - 语义清晰，便于在浏览器 devtools 中直接切换调试。
 *
 * 与 antd 主题的关系：
 *   ConfigProvider 的 theme 由 getAntdTheme() 依据本上下文的两个值构造，
 *   因此「CSS 变量」与「antd token」始终同步切换，不会出现
 *   「组件样式变了、页面底色没变」的割裂（见 main.tsx）。
 *
 * 数据流向：
 *   localStorage ──读取──▶ 模块顶层（防闪烁首屏应用）
 *   UiPrefsProvider 状态 ──▶ <html> 属性 ──▶ CSS 变量 ──▶ 全站样式
 *                        └─▶ getAntdTheme ──▶ ConfigProvider ──▶ antd 组件
 */

import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

/** 外观风格：neu = 新拟物（默认），classic = 改造前的经典样式 */
export type UiStyle = 'neu' | 'classic';
/** 明暗模式 */
export type ColorMode = 'light' | 'dark';

const STORAGE_KEY_STYLE = 'medpal.ui.uiStyle';
const STORAGE_KEY_COLOR = 'medpal.ui.colorMode';

/** 默认外观风格：新拟物（本项目的目标视觉） */
export const DEFAULT_UI_STYLE: UiStyle = 'neu';
/** 默认明暗模式：浅色（首次访问且系统无偏好时的兜底） */
export const DEFAULT_COLOR_MODE: ColorMode = 'light';

const UI_STYLES: readonly UiStyle[] = ['neu', 'classic'];
const COLOR_MODES: readonly ColorMode[] = ['light', 'dark'];

/**
 * 读取本地存储的偏好值。
 * 存储被禁用（隐私模式 / 策略限制）或值非法时静默回落到兜底值 ——
 * 外观偏好不应成为功能可用性的阻塞点。
 */
function readStored<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw && (allowed as readonly string[]).includes(raw)) return raw as T;
  } catch (err) {
    console.warn('[UI 偏好] 读取本地存储失败，使用默认值:', err);
  }
  return fallback;
}

/** 读取系统级明暗偏好（首次访问时作为默认值，尊重用户操作系统设置） */
function detectSystemColorMode(): ColorMode {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch (err) {
    console.warn('[UI 偏好] 无法读取系统明暗偏好，使用浅色:', err);
    return DEFAULT_COLOR_MODE;
  }
}

/**
 * 把偏好写入根元素属性。
 * 同时设置 color-scheme，让滚动条、原生表单控件、系统 UI 跟随明暗切换
 * （否则深色下会出现刺眼的白色滚动条）。
 */
export function applyUiPrefs(style: UiStyle, mode: ColorMode): void {
  const root = document.documentElement;
  root.setAttribute('data-ui-style', style);
  root.setAttribute('data-color-mode', mode);
  root.style.colorScheme = mode;
}

// ── 首屏防闪烁：模块加载即应用（早于 ReactDOM 渲染）────────────────
const initialStyle = readStored(STORAGE_KEY_STYLE, UI_STYLES, DEFAULT_UI_STYLE);
const initialColor = readStored(STORAGE_KEY_COLOR, COLOR_MODES, detectSystemColorMode());
applyUiPrefs(initialStyle, initialColor);

interface UiPrefsValue {
  /** 当前外观风格 */
  uiStyle: UiStyle;
  /** 当前明暗模式 */
  colorMode: ColorMode;
  /** 便捷判断：是否为新拟物 */
  isNeu: boolean;
  /** 便捷判断：是否为深色 */
  isDark: boolean;
  setUiStyle: (style: UiStyle) => void;
  setColorMode: (mode: ColorMode) => void;
  /** 在新拟物 / 经典之间切换 */
  toggleUiStyle: () => void;
  /** 在浅色 / 深色之间切换 */
  toggleColorMode: () => void;
  /** 恢复默认外观（新拟物 + 浅色） */
  resetUiPrefs: () => void;
}

const UiPrefsContext = createContext<UiPrefsValue>(null!);

/** 读取界面偏好；必须在 UiPrefsProvider 内使用 */
export const useUiPrefs = () => useContext(UiPrefsContext);

export const UiPrefsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [uiStyle, setUiStyleState] = useState<UiStyle>(initialStyle);
  const [colorMode, setColorModeState] = useState<ColorMode>(initialColor);

  // 状态变化 → 同步根属性与本地存储
  useEffect(() => {
    applyUiPrefs(uiStyle, colorMode);
    try {
      localStorage.setItem(STORAGE_KEY_STYLE, uiStyle);
      localStorage.setItem(STORAGE_KEY_COLOR, colorMode);
    } catch (err) {
      // 写入失败不影响本次会话的显示效果，仅无法记忆
      console.warn('[UI 偏好] 持久化失败（本地存储不可用）:', err);
    }
  }, [uiStyle, colorMode]);

  const value = useMemo<UiPrefsValue>(
    () => ({
      uiStyle,
      colorMode,
      isNeu: uiStyle === 'neu',
      isDark: colorMode === 'dark',
      setUiStyle: setUiStyleState,
      setColorMode: setColorModeState,
      toggleUiStyle: () => setUiStyleState((s) => (s === 'neu' ? 'classic' : 'neu')),
      toggleColorMode: () => setColorModeState((m) => (m === 'light' ? 'dark' : 'light')),
      resetUiPrefs: () => {
        setUiStyleState(DEFAULT_UI_STYLE);
        setColorModeState(DEFAULT_COLOR_MODE);
      },
    }),
    [uiStyle, colorMode],
  );

  return <UiPrefsContext.Provider value={value}>{children}</UiPrefsContext.Provider>;
};
