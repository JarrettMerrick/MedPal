#!/usr/bin/env node
/**
 * 全站截图回归（新拟物/经典 × 浅色/深色）
 * ====================================
 * 用途：验证四种外观组合下页面均正常渲染，并作为改造验收与后续版本回归的证据。
 *
 * 依赖：agent-browser CLI（`npm i -g agent-browser && agent-browser install`）
 *
 * 用法：
 *   node frontend/scripts/screenshot-regression.mjs
 *   node frontend/scripts/screenshot-regression.mjs --base http://localhost:5173
 *   node frontend/scripts/screenshot-regression.mjs --out .screenshots
 *
 * 可选（截图需登录的页面时）：
 *   设置环境变量 MEDPAL_USER / MEDPAL_PASS，脚本会先登录，再截图工作台等页面。
 *   未设置时只截公开页（登录页），仍可验证四种外观组合与可回退性。
 *
 * 实现要点：
 *   - 通过 `eval` 写入 localStorage（medpal.ui.uiStyle / medpal.ui.colorMode）后刷新，
 *     驱动 UiPrefsContext 切换外观 —— 与用户真实操作路径一致（偏好会被持久化，因此
 *     脚本结束前会复位为默认值，避免影响本机浏览器下次访问的观感）。
 *   - 每种组合的产物独立命名，便于横向对比。
 */

import { execFileSync, execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * 解析 agent-browser 的真实可执行文件路径。
 *
 * 原因：全局 npm 包在 Windows 上落地为 `agent-browser.cmd`，
 * 而 `execFileSync` 不经过 shell，直接用命令名会抛 ENOENT。
 * 这里用 where/which 取绝对路径（Windows 下优先 .cmd，Node 会自动用 cmd.exe 执行），
 * 从而**既能找到命令、又不必开启 `shell: true`** —— 后者会让参数中的
 * JS 字符串（含引号）被 shell 二次解析，存在注入风险。
 */
function resolveAgentBrowser() {
  const locate = process.platform === 'win32' ? 'where agent-browser' : 'which agent-browser';
  try {
    const lines = execSync(locate, { encoding: 'utf8' })
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    return lines.find((p) => p.toLowerCase().endsWith('.cmd')) || lines[0] || 'agent-browser';
  } catch {
    // 未安装时给出明确指引，而不是让后续调用抛出难懂的 ENOENT
    console.error('未找到 agent-browser。请先安装：');
    console.error('  npm i -g agent-browser && agent-browser install');
    process.exit(1);
  }
}

const AB = resolveAgentBrowser();

// ---- 参数解析 ----
const argv = process.argv.slice(2);
const getArg = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i !== -1 && argv[i + 1] ? argv[i + 1] : fallback;
};

const BASE = getArg('base', 'http://localhost:5173');
const OUT = resolve(getArg('out', '.screenshots'));
const USER = process.env.MEDPAL_USER;
const PASS = process.env.MEDPAL_PASS;

/** 四种外观组合 */
const COMBOS = [
  { uiStyle: 'neu', colorMode: 'light', label: 'neumorphism-light' },
  { uiStyle: 'neu', colorMode: 'dark', label: 'neumorphism-dark' },
  { uiStyle: 'classic', colorMode: 'light', label: 'classic-light' },
  { uiStyle: 'classic', colorMode: 'dark', label: 'classic-dark' },
];

/** 公开页（无需登录） */
const PUBLIC_PAGES = [{ path: '/login', name: 'login' }];

/** 需登录的页面（仅当提供凭据时截图） */
const PRIVATE_PAGES = [
  { path: '/dashboard', name: 'dashboard' },
  { path: '/staff', name: 'staff-list' },
  { path: '/signages', name: 'signage-list' },
  { path: '/signages/overview', name: 'signage-overview' },
  { path: '/design-files', name: 'design-files' },
  { path: '/data', name: 'data-manage' },
  { path: '/system-settings', name: 'system-settings' },
];

/**
 * 统一执行入口。
 *
 * Windows 上 `agent-browser` 是 `.cmd` 批处理，Node 的 execFileSync 直接调用会失败，
 * 因此需要 `shell: true` 让系统 shell 代为解析（Node 20+ 在 Windows 上默认不再
 * 自动用 cmd.exe 包装 .cmd）。此处传入的参数全部由本脚本内部构造（命令行参数里
 * 只有 base URL 来自外部，且仅用于拼接 URL），不接受用户提供的任意命令片段。
 */
function ab(args, options = {}) {
  return execFileSync(AB, args, {
    encoding: 'utf8',
    shell: process.platform === 'win32',
    stdio: options.quiet ? 'pipe' : 'inherit',
    timeout: 60000,
  });
}

function abQuiet(args) {
  return execFileSync(AB, args, {
    encoding: 'utf8',
    shell: process.platform === 'win32',
    stdio: 'pipe',
    timeout: 60000,
  });
}

/** 打开指定路径并等待渲染 */
function goto(path) {
  ab(['open', `${BASE}${path}`], { quiet: true });
  try {
    ab(['wait', '--load', 'load'], { quiet: true });
  } catch {
    // 等待失败不阻塞截图（SPA 可能长时间不进入 idle）
  }
  // 给 React 与 antd 样式注入留出稳定时间
  abQuiet(['wait', '900']);
}

/** 写入外观偏好并刷新，使其生效 */
function applyAppearance(uiStyle, colorMode) {
  abQuiet([
    'eval',
    `localStorage.setItem('medpal.ui.uiStyle','${uiStyle}');` +
      `localStorage.setItem('medpal.ui.colorMode','${colorMode}');` +
      `location.reload();`,
  ]);
  abQuiet(['wait', '1200']);
}

function shoot(file) {
  ab(['screenshot', file], { quiet: true });
  console.log(`  ✓ ${file}`);
}

function tryLogin() {
  if (!USER || !PASS) return false;
  try {
    goto('/login');
    abQuiet(['fill', 'input[type="text"]', USER]);
    abQuiet(['fill', 'input[type="password"]', PASS]);
    abQuiet(['press', 'Enter']);
    abQuiet(['wait', '2500']);
    console.log('  ✓ 已登录，将额外截图需鉴权页面');
    return true;
  } catch (err) {
    console.warn('  ! 登录失败，仅截图公开页：', err.message);
    return false;
  }
}

// ---- 主流程 ----
mkdirSync(OUT, { recursive: true });
console.log(`目标站点：${BASE}`);
console.log(`输出目录：${OUT}\n`);

let loggedIn = false;
const pages = [...PUBLIC_PAGES];

for (const combo of COMBOS) {
  console.log(`[${combo.label}]`);
  applyAppearance(combo.uiStyle, combo.colorMode);

  // 登录只在首个组合里做一次（会话在 daemon 中保持）
  if (!loggedIn && combo === COMBOS[0]) {
    loggedIn = tryLogin();
    if (loggedIn) pages.push(...PRIVATE_PAGES);
    applyAppearance(combo.uiStyle, combo.colorMode);
  }

  for (const page of pages) {
    goto(page.path);
    shoot(`${OUT}/${combo.label}__${page.name}.png`);
  }
  console.log('');
}

// ---- 复位偏好，避免影响本机浏览器下次访问 ----
applyAppearance('neu', 'light');
ab(['close'], { quiet: true });

console.log('完成。四种组合 × 页面的截图已生成于：');
console.log(`  ${OUT}`);
console.log('提示：本地历史中记录的偏好已复位为「新拟物 + 浅色」。');
