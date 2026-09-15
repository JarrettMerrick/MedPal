// [新增 2026-09-09] 标识历史版本字段中文名与枚举值翻译
// 背景：SignageHistory.field_name 存储的是数据库字段名（如 installation_photo），
// old_value/new_value 对枚举字段（status/validity_type）存储英文代码值，
// 历史版本弹窗（SignageDetail）与变更历史页（SignageHistoryPage）统一使用本映射展示中文，
// 避免界面出现 raw 代码值。

/** 标识字段名 → 中文名（key 与后端 Signage 模型字段一致） */
export const SIGNAGE_FIELD_LABELS: Record<string, string> = {
  code: '编码',
  name: '名称',
  category: '分类',
  category_type: '类别',
  material: '材质',
  size_spec: '规格尺寸',
  campus: '院区',
  building: '楼栋',
  floor: '楼层',
  // [新增 2026-09-12] 具体区域（多选，逗号分隔）；与 zone_type 的「所属区域」区分显示
  area: '区域',
  zone_type: '所属区域',
  location_desc: '安装位置描述',
  display_text_cn: '中文文本',
  display_text_en: '英文文本',
  department_id: '所属科室',
  status: '状态',
  oa_number: 'OA单号',
  manufacturer: '制作厂商',
  vendor_contact: '厂商联系方式',
  install_date: '安装日期',
  warranty_expire: '质保到期日',
  validity_type: '有效期类型',
  validity_until: '有效期至',
  design_photo: '设计文件',
  installation_photo: '现场照片',
};

/** 枚举字段的值翻译（key 与后端字段取值一致） */
const SIGNAGE_VALUE_LABELS: Record<string, Record<string, string>> = {
  status: {
    normal: '正常',
    damaged: '轻微破损',
    severely_damaged: '严重损坏',
    repair_in_progress: '维修处理中',
    removed: '已拆除',
  },
  validity_type: {
    long_term: '长期',
    temporary: '临时',
  },
};

/** 字段名转中文；未知字段回退原值；空字段返回空串 */
export const signageFieldLabel = (field?: string | null): string =>
  field ? (SIGNAGE_FIELD_LABELS[field] || field) : '';

/** 字段值转中文：按字段枚举字典翻译，非枚举字段原样返回；空值返回空串 */
export const formatSignageFieldValue = (field?: string | null, value?: string | null): string => {
  if (value === null || value === undefined || value === '') return '';
  const dict = field ? SIGNAGE_VALUE_LABELS[field] : undefined;
  return (dict && dict[value]) || value;
};
