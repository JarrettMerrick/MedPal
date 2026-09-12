// [新增 2026-09-05] 标识状态常量：取值与后端 signages.status 字段完全一致，
// 供标识巡检、平面标记、标识列表等处统一调用，避免各页面硬编码造成口径不一致

export interface SignageStatusOption {
  value: string;
  label: string;
  color: string;
}

export const SIGNAGE_STATUS_OPTIONS: SignageStatusOption[] = [
  { value: 'normal', label: '正常', color: 'green' },
  { value: 'damaged', label: '轻微破损', color: 'gold' },
  { value: 'severely_damaged', label: '严重损坏', color: 'red' },
  // [新增 2026-09-08] 维修处理中：预警模块发起维修后的过渡状态，完成维修后回到正常
  { value: 'repair_in_progress', label: '维修处理中', color: 'processing' },
  { value: 'removed', label: '已拆除', color: 'default' },
];

export const SIGNAGE_STATUS_MAP: Record<string, { color: string; label: string }> =
  SIGNAGE_STATUS_OPTIONS.reduce(
    (acc, s) => ({ ...acc, [s.value]: { color: s.color, label: s.label } }),
    {} as Record<string, { color: string; label: string }>,
  );
