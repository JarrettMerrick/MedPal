// [新增 2026-09-05] 标识状态常量：取值与后端 signages.status 字段完全一致，
// 供标识巡检、平面标记、标识列表等处统一调用，避免各页面硬编码造成口径不一致
//
// [重构 2026-09-21 / 代码质量审计 Q-8] 此前同一套状态枚举在前端有**三处定义**：
//   ① 本文件
//   ② pages/signages/SignageDetail.tsx 的 STATUS_MAP
//   ③ pages/signages/SignageForm.tsx 的 STATUS_OPTIONS
// 三处口径已经开始漂移 —— 其中 SignageForm 的副本**缺少 repair_in_progress**，
// 导致编辑一个"维修处理中"的标识时，状态下拉框无法回显该状态。
// 现统一收敛到本文件；各页面只消费，不再各自定义。
//
// 另外，本文件此前**没有任何模块引用它**（三处都在用各自的本地副本），
// 所以这次得以按"能同时覆盖三处用法"的目标重新设计字段，而不必迁就旧结构。
//
// ⚠️ 维护约定：**新增状态时只改这里**。若某页面需要额外的展示维度，
// 请在此处扩展字段，而不是在页面里另建一份映射 —— 否则又会回到"多份定义漂移"的老路。

export interface SignageStatusOption {
  /** 与后端 signages.status 一致的取值（表单提交 / 接口比对用） */
  value: string;
  /** 中文显示名 */
  label: string;
  /** antd Tag / Badge 的色名（'green' / 'gold' / 'processing' ...） */
  tagColor: string;
  /** 具体色值（内联样式、图表配色用）。注意与 tagColor 的区别：这里是 #RRGGBB */
  color: string;
  /** 详情页状态胶囊的类名（配套 CSS 定义在 SignageDetail 页面内） */
  className: string;
}

export const SIGNAGE_STATUS_OPTIONS: SignageStatusOption[] = [
  {
    value: 'normal', label: '正常',
    tagColor: 'green', color: '#1F7A4B', className: 'status-ok',
  },
  {
    value: 'damaged', label: '轻微破损',
    tagColor: 'gold', color: '#A16207', className: 'status-damaged',
  },
  {
    // [修复 2026-09-09] 文案统一为「严重损坏」，与各页面口径一致
    value: 'severely_damaged', label: '严重损坏',
    tagColor: 'red', color: 'var(--danger)', className: 'status-severe',
  },
  {
    // [新增 2026-09-08] 维修处理中：预警模块发起维修后的过渡状态，完成维修后回到正常。
    // ⚠️ 该状态此前在 SignageForm 的副本中缺失，本次统一后一并补齐。
    value: 'repair_in_progress', label: '维修处理中',
    tagColor: 'processing', color: '#1677FF', className: 'status-repair',
  },
  {
    value: 'removed', label: '已拆除',
    tagColor: 'default', color: '#6B7280', className: 'status-removed',
  },
];

/**
 * value → 完整信息 的映射。
 * 替代 SignageDetail.tsx 中的本地 STATUS_MAP（字段名与之一致，可直接替换）。
 */
export const SIGNAGE_STATUS_MAP: Record<string, SignageStatusOption> =
  SIGNAGE_STATUS_OPTIONS.reduce(
    (acc, s) => ({ ...acc, [s.value]: s }),
    {} as Record<string, SignageStatusOption>,
  );

/**
 * 表单下拉选项（value + label）。
 * 替代 SignageForm.tsx 中的本地 STATUS_OPTIONS。
 */
export const SIGNAGE_STATUS_SELECT_OPTIONS: { value: string; label: string }[] =
  SIGNAGE_STATUS_OPTIONS.map((s) => ({ value: s.value, label: s.label }));

/**
 * 由状态取值取中文名，取不到时**回落到原值**。
 * 统一的回落行为可以避免各页面各写一个 `|| '正常'` 之类的默认值 ——
 * 那种写法会把"未知状态"悄悄显示成「正常」，掩盖数据异常。
 * 此处选择回显原始取值，让异常状态可见。
 */
export function getSignageStatusLabel(value: string | null | undefined): string {
  if (!value) return '-';
  return SIGNAGE_STATUS_MAP[value]?.label ?? value;
}
