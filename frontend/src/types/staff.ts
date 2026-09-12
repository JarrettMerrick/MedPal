// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

export interface Staff {
  employee_id: string;
  name: string;
  work_type: 'doctor' | 'nurse' | 'technician' | 'admin';
  education: string | null;
  title: string | null;
  department: string | null;
  position: string | null;
  expertise_short: string | null;
  expertise_standard: string | null;
  social_appointments: string | null;
  honors: string | null;
  remarks: string | null;
  front_photo: string | null;
  side_photo: string | null;
  status: 'active' | 'resigned';
  // [新增 2026-09-11] 离职档案（仅离职人员有值）
  resigned_at?: string | null;
  resign_reason?: string | null;
  resigned_by?: string | null;
  updated_by: string | null;
  updated_at: string | null;
  // [新增 2026-09-11] 待审核变更提示（无待审时为 null/undefined）：
  // 用于在人员列表/详情显著位置提示「XX 未审核」
  pending_change?: StaffPendingBadge | null;
}

/** [新增 2026-09-11] 某人员的待审核变更提示（立即生效 + 追认审核） */
export interface StaffPendingBadge {
  count: number;
  id: number;
  review_level: 'none' | 'dept' | 'admin';
  level_label: string;
  change_summary: string | null;
  changed_labels: string[];
  submitted_by_name: string | null;
  submitted_at: string | null;
  escalated: boolean;
}

export interface StaffListResponse {
  total: number;
  items: Staff[];
  page: number;
  page_size: number;
  /** [新增 2026-09-11] 离职人员保留期统计口径（仅 /staff/resigned 返回） */
  stats?: {
    total: number;          // 离职总人数
    in_archive: number;     // 在档（未满保留期）
    archived: number;       // 已满保留期（仅计入统计）
    retention_days: number; // 保留期天数
    cutoff: string;         // 保留期截止时间（UTC ISO）
    scope: string;
  } | null;
}

export const WORK_TYPE_OPTIONS = [
  { value: 'doctor', label: '医生' },
  { value: 'nurse', label: '护士' },
  { value: 'technician', label: '技师' },
  { value: 'admin', label: '行政' },
] as const;

export const WORK_TYPE_LABELS: Record<string, string> = {
  doctor: '医生',
  nurse: '护士',
  technician: '技师',
  admin: '行政',
};

/**
 * 工种语义色（antd 预设色名，用于 Tag 标签）
 * 作为全系统工种配色的唯一来源，禁止在页面中硬编码其他色名。
 */
export const WORK_TYPE_COLOR: Record<string, string> = {
  doctor: 'blue',
  nurse: 'magenta',
  technician: 'purple',
  admin: 'gold',
};

/**
 * 工种主题色（hex，用于卡片左侧色条，与 WORK_TYPE_COLOR 一一对应）
 * 色条仅 4px，不影响卡片整体白底统一性，又能一眼区分工种。
 */
export const WORK_TYPE_HEX: Record<string, string> = {
  doctor: '#1677ff',      // antd blue
  nurse: '#eb2f96',       // antd magenta
  technician: '#722ed1',  // antd purple
  admin: '#faad14',       // antd gold
};

export const WORK_TYPE_DEPT_CATEGORY: Record<string, string> = {
  doctor: '临床专科',
  nurse: '护理病区',
  technician: '临床专科',
  admin: '行政科室',
};

/**
 * 科室类别主题色（hex，用于科室卡片左侧色条）
 * 与工种语义色呼应：临床专科→蓝（医生/技师）、护理病区→粉（护士）、行政科室→金（行政），
 * 让员工与科室两类页面在视觉上建立联想，全局更统一。
 */
export const DEPT_CATEGORY_HEX: Record<string, string> = {
  '临床专科': '#1677ff',  // 呼应 doctor/technician
  '护理病区': '#eb2f96',  // 呼应 nurse
  '行政科室': '#faad14',  // 呼应 admin
};

export const TITLE_OPTIONS_BY_WORK_TYPE: Record<string, string[]> = {
  doctor: ['主任医师', '副主任医师', '主治医师', '住院医师'],
  technician: ['主任技师', '副主任技师', '主管技师', '技师', '技士'],
  nurse: ['主任护师', '副主任护师', '主管护师', '护师', '护士'],
  admin: ['高级行政专员', '行政专员', '行政助理'],
};
