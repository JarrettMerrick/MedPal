import api, { uploadApi } from './client';

export interface Signage {
  id: number;
  code: string;
  name: string;
  category: string;
  // [修复 2026-09-04] 新增类别类型字段：标识标牌/平面宣传
  category_type: string;
  material?: string;
  size_spec?: string;
  install_date?: string;
  warranty_expire?: string;
  // [新增 2026-09-05] 标识有效期：long_term 长期 / temporary 临时（validity_until 为到期日）
  validity_type?: string;
  validity_until?: string;
  // [修复 2026-09-04] 新增所属区域类型字段：院区导视/宣传、楼栋导视/宣传、楼层导视/宣传
  zone_type: string;
  campus?: string;
  building?: string;
  floor?: string;
  /** [新增 2026-09-12] 所属区域（选填，多选用英文逗号分隔；仅「楼层导视/宣传」可填） */
  area?: string;
  location_desc?: string;
  display_text_cn?: string;
  display_text_en?: string;
  department_id?: number;
  // [新增 2026-09-08] 所属科室名称（后端关联填充，便于展示）
  department_name?: string;
  status: string;
  oa_number?: string;
  manufacturer?: string;
  vendor_contact?: string;
  // [调整 2026-09-17] 允许 null：解除关联时前端会**显式提交 null**（清空字段），
  // 若类型只允许 undefined，调用方无法表达"清空"语义
  design_photo?: string | null;
  installation_photo?: string | null;
  // [新增 2026-09-17] 文件库引用：指向「文件管理」中的设计文件记录（引用共享）
  design_file_id?: number | null;
  /**
   * [新增 2026-09-17] 引用的设计文件在「文件管理」中的**使用名**（后端按 design_file_id 关联填充）。
   * 展示设计文件时优先使用它，避免显示 design_photo 路径中的原始落盘名
   * （形如 RC-XX-0-001_design_20260917_101530_ab12cd34.ai）。
   * 未引用文件库（directly 上传的旧数据）时为空，前端回退到路径文件名。
   */
  design_file_name?: string | null;
  // [新增 2026-09-07] 最近一次巡检日期
  last_inspection_date?: string;
  created_by?: string;
  created_at: string;
  updated_by?: string;
  updated_at: string;
}

export interface SignageListResponse {
  total: number;
  items: Signage[];
  page: number;
  page_size: number;
}

export interface SignageHistory {
  id: number;
  signage_id: number;
  field_name?: string;
  old_value?: string;
  new_value?: string;
  oa_number?: string;
  changed_by?: string;
  changed_at: string;
  // [修复 2026-09-04] 新增 snapshot 字段，存储完整标识快照
  snapshot?: string;
}

export interface SignageHistoryListResponse {
  total: number;
  items: SignageHistory[];
  page: number;
  page_size: number;
}

export interface FloorPlan {
  id: number;
  name: string;
  // [修复 2026-09-05] 平面类别取代原 type：院区平面/楼层平面
  category: string;
  // [修复 2026-09-05] 允许 null：切换平面类别时需显式清空楼栋/楼层关联（null 才会被后端写入）
  campus?: string | null;
  building?: string | null;
  floor?: string | null;
  image_url?: string;
  version: number;
  is_active: boolean;
  created_at: string;
  // [修复 2026-09-05] 新增 floor_code 关联楼层编号与 description 描述
  floor_code?: string | null;
  description?: string;
  // [修复 2026-09-05] 新增 floor_id：关联院区管理中的楼层记录（floors.id）
  floor_id?: number | null;
}

export interface SignagePoint {
  id: number;
  signage_id: number;
  floor_plan_id: number;
  x_percent: number;
  y_percent: number;
  pin_icon?: string;
  pin_color?: string;
  // [修复 2026-09-05] 后端随点位返回的标识信息，用于按「分类形状+颜色」渲染标记，
  // 不再依赖绑定弹窗的分页标识列表（已标记的标识会被 exclude_marked 过滤掉）
  signage_category?: string;
  signage_code?: string;
  signage_name?: string;
}

export interface SignagePhoto {
  id: number;
  signage_id: number;
  photo_type?: string;
  photo_url?: string;
  caption?: string;
  uploaded_by?: string;
  uploaded_at: string;
}

// [新增 2026-09-05] 标识巡检相关 API
export interface SignageInspectionRecord {
  id: number;
  signage_id: number;
  signage_code?: string;
  signage_name?: string;
  signage_status?: string;
  result: string;
  inspection_date?: string;
  inspector?: string;
  notes?: string;
  // [新增 2026-09-07] 巡检现场照片（客户端压缩后上传，可选）
  photo?: string;
  created_at: string;
}

// [新增 2026-09-08] 巡检越权科室时后端返回的提示结构
export interface InspectionDepartmentWarning {
  ok: false;
  warning: true;
  message: string;
}

// ============================================================
// [新增 2026-09-08] 预警处理：标识维修流程
//   状态异常 --发起维修--> 维修处理中 --完成维修(可选照片)--> 正常
// ============================================================
export type RepairParty = 'vendor' | 'engineering';

// 发起维修：供应商维修必选供应商（OA 单号可选）；工程部维修可直接确认
export const startSignageRepair = (data: {
  signage_id: number;
  repair_party: RepairParty;
  oa_number?: string;
  supplier_id?: number;
}): Promise<{ id: number; signage_id: number; repair_party: string; supplier_name?: string; oa_number?: string; status: string }> =>
  api.post('/signage-alerts/repairs/start', data).then((r) => r.data);

// 上传维修完成照片（客户端已压缩），返回相对路径；完成维修前调用（可选）
export const uploadRepairPhoto = (file: File | Blob): Promise<{ file_path: string }> => {
  const fd = new FormData();
  fd.append('file', file);
  return api.post('/signage-alerts/repairs/photo', fd).then((r) => r.data);
};

// 完成维修：若上传照片则后端同步替换标识安装现场照片；预警状态回到正常
export const completeSignageRepair = (
  id: number,
  photo?: string,
): Promise<{ id: number; signage_id: number; repair_photo?: string; status: string }> =>
  api.post(`/signage-alerts/repairs/${id}/complete`, { photo }).then((r) => r.data);

// [新增 2026-09-09] 标识维修记录（详情页「维修记录」弹窗查询）
// repair_photo_before：维修前照片（发起维修时自动取自最近一次巡检上传的现场照片）
// repair_photo：维修后照片（完成维修时上传，可能为空）
export interface SignageRepairRecord {
  id: number;
  signage_id: number;
  repair_party: string;
  supplier_name?: string;
  oa_number?: string;
  repair_photo_before?: string;
  repair_photo?: string;
  started_by?: string;
  started_at?: string;
  completed_by?: string;
  completed_at?: string;
}

// 查询某标识的全部维修记录（按发起时间倒序），权限与巡检历史一致（标识查看）
export const getSignageRepairs = (signageId: number): Promise<SignageRepairRecord[]> =>
  api.get('/signage-alerts/repairs', { params: { signage_id: signageId } }).then((r) => r.data);

// ============================================================
// [新增 2026-09-14] 预警标识清单（标识标记页高亮预警标识用）
// ============================================================
export interface AlertedSignageItem {
  id: number;
  /** 该标识命中的预警类型（中文），用于在标记详情中说明预警原因 */
  alerts: string[];
}

/** 处于预警状态的标识；判定口径与 /signage-alerts/summary 一致，但不做条数截断 */
export const getAlertedSignages = (): Promise<AlertedSignageItem[]> =>
  api.get('/signage-alerts/alerted-signage-ids').then((r) => r.data.items);

// [删除 2026-09-17] 标识预警汇总（SignageAlertSummary / getSignageAlertSummary）已移除：
// 「标识预警」页与菜单红点整体下线，状态异常标识与维修处理统一在「标识维修」页
// （GET /signage-repairs 的「待维修 / 维修处理中」行）展示与处理。

// ============================================================
// [新增 2026-09-09] 标识总览（/signage-overview）与维修记录（/signage-repairs）
// ============================================================
export interface OverviewKpi {
  total: number;
  normal: number;
  damaged: number;
  severely_damaged: number;
  repair_in_progress: number;
  removed: number;
  inspection_due_soon: number;
  inspection_overdue: number;
  temporary_expiring: number;
}

export interface DistributionItem { name: string; count: number }

export interface RepairSummary {
  month_started: number;
  month_completed: number;
  in_progress: number;
  avg_hours: number;
  party_vendor: number;
  party_engineering: number;
}

export interface OverviewRecentRepair {
  id: number; signage_id: number; code?: string; name?: string;
  repair_party: string; party_label: string; supplier_name?: string; oa_number?: string;
  status: 'in_progress' | 'completed';
  started_at?: string; completed_at?: string;
}

export interface OverviewRecentInspection {
  id: number; signage_id: number; code?: string; name?: string;
  result: string; result_label: string; inspector?: string; created_at?: string; photo?: string;
}

export interface OverviewAlert { type: string; id: number; code?: string; name?: string; info: string }

export interface SignageOverviewData {
  kpi: OverviewKpi;
  category_distribution: DistributionItem[];
  campus_distribution: DistributionItem[];
  building_top: DistributionItem[];
  repair_summary: RepairSummary;
  recent_repairs: OverviewRecentRepair[];
  recent_inspections: OverviewRecentInspection[];
  recent_alerts: OverviewAlert[];
  generated_at: string;
}

export interface InspectionTrendItem { date: string; count: number }

export interface InspectionTrendResult { start_date: string; end_date: string; items: InspectionTrendItem[] }

/** 标识总览聚合数据（KPI/分布/维修概况/最近动态），60 秒轮询调用 */
export const getSignageOverview = (): Promise<SignageOverviewData> =>
  api.get('/signages/overview').then((r) => r.data);

/** 巡检提交量趋势（按北京日期逐日统计，最多 90 天） */
export const getInspectionTrend = (params: { start_date: string; end_date: string }): Promise<InspectionTrendResult> =>
  api.get('/signages/overview/inspection-trend', { params }).then((r) => r.data);

export interface SignageRepairListItem {
  id: number;
  signage_id: number;
  code?: string;
  name?: string;
  category?: string;
  campus?: string;
  building?: string;
  floor?: string;
  repair_party: string;
  party_label: string;
  supplier_name?: string;
  oa_number?: string;
  repair_photo_before?: string;
  repair_photo?: string;
  started_by?: string;
  /** [新增 2026-09-17] 发起人姓名（后端按工号回查人员表；查不到时为空） */
  started_by_name?: string;
  started_at?: string;
  completed_by?: string;
  /** [新增 2026-09-17] 完成人姓名 */
  completed_by_name?: string;
  completed_at?: string;
  duration_hours?: number | null;
  /**
   * [调整 2026-09-17] 新增 pending（待维修）：
   * 标识状态为轻微破损 / 严重损坏且尚未发起维修，可直接发起维修。
   */
  status: 'pending' | 'in_progress' | 'completed';
  status_label: string;
  /** [新增 2026-09-17] 标识当前状态（pending 行用于区分损坏等级） */
  signage_status?: string | null;
  /** [新增 2026-09-17] 标识当前状态中文（轻微破损 / 严重损坏） */
  signage_status_label?: string | null;
}

export interface SignageRepairListResponse {
  total: number; page: number; page_size: number; items: SignageRepairListItem[];
}

export interface RepairListParams {
  page?: number;
  page_size?: number;
  keyword?: string;
  signage_id?: number;
  start_date?: string;
  end_date?: string;
  repair_party?: 'vendor' | 'engineering';
  supplier_id?: number;
  /** [调整 2026-09-17] 支持按「待维修 / 维修处理中 / 已完成」筛选 */
  status?: 'pending' | 'in_progress' | 'completed';
}

const buildRepairQuery = (params: RepairListParams): string => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.append(k, String(v));
  });
  const s = qs.toString();
  return s ? `?${s}` : '';
};

/** 分页查询全部标识维修记录（多条件筛选） */
export const getSignageRepairList = (params: RepairListParams): Promise<SignageRepairListResponse> =>
  api.get('/signage-repairs', { params }).then((r) => r.data);

/** 按筛选条件统计条数（导出确认弹窗展示导出范围） */
export const getSignageRepairCount = (params: RepairListParams): Promise<{ total: number }> =>
  api.get('/signage-repairs/count', { params }).then((r) => r.data);

/** 按当前筛选条件导出维修记录（xlsx/csv），返回可下载的 Blob URL */
export const getRepairsExportUrl = (params: RepairListParams, format: 'xlsx' | 'csv'): string =>
  `/api/signage-repairs/export.${format}${buildRepairQuery(params)}`;

// 按标识编码精确查询（移动巡检手输/扫码用）
export const getSignageByCode = (code: string): Promise<Signage> =>
  api.get(`/signages/by-code/${encodeURIComponent(code)}`).then((r) => r.data);

// 提交巡检：巡检结果同步更新标识现有 status 字段
export const createSignageInspection = (data: {
  code: string;
  result: string;
  notes?: string;
  // [新增 2026-09-07] 现场照片路径（可选，客户端压缩后先上传获得）
  photo?: string;
}): Promise<SignageInspectionRecord | InspectionDepartmentWarning> =>
  api.post('/signage-inspections', data).then((r) => r.data);

// [新增 2026-09-07] 上传巡检现场照片（客户端已完成压缩），返回相对路径
export const uploadInspectionPhoto = (code: string, file: File | Blob): Promise<{ file_path: string }> => {
  const fd = new FormData();
  fd.append('file', file);
  return api.post(`/signage-inspections/photo/${encodeURIComponent(code)}`, fd).then((r) => r.data);
};

// 巡检历史查询：支持时间范围、标识编号、巡检人员筛选
export const getSignageInspections = (params: {
  page?: number;
  page_size?: number;
  code?: string;
  inspector?: string;
  start_date?: string;
  end_date?: string;
}): Promise<{ total: number; items: SignageInspectionRecord[]; page: number; page_size: number }> =>
  api.get('/signage-inspections', { params }).then((r) => r.data);
// [新增 2026-09-05] 标识巡检相关 API 结束

export const getSignageList = (params: {
  page?: number;
  page_size?: number;
  search?: string;
  category?: string;
  status?: string;
  campus?: string;
  building?: string;
  // [新增 2026-09-07] 楼层筛选：与列表页筛选栏联动
  floor?: string;
  // [修复 2026-09-05] 标记管理：排除已被标记过的标识（每个标识仅可被标记一次）
  exclude_marked?: boolean;
}): Promise<SignageListResponse> =>
  api.get('/signages', { params }).then((r) => r.data);

export const getSignage = (id: number): Promise<Signage> =>
  api.get(`/signages/${id}`).then((r) => r.data);

export const createSignage = (data: Partial<Signage>): Promise<Signage> =>
  api.post('/signages', data).then((r) => r.data);

// [修复 2026-09-03] OA单号改为选填，支持空字符串
// [新增 2026-09-09] record_history：仅详情页「版本更新」入口传 true 时记录历史版本；普通编辑不记录
export const updateSignage = (
  id: number,
  data: Partial<Signage>,
  oa_number?: string,
  record_history?: boolean,
): Promise<Signage> =>
  api.put(`/signages/${id}`, data, {
    params: {
      oa_number: oa_number || '',
      ...(record_history ? { record_history: true } : {}),
    },
  }).then((r) => r.data);

export const deleteSignage = (id: number): Promise<void> =>
  api.delete(`/signages/${id}`).then((r) => r.data);

export const getSignageHistory = (id: number, params?: {
  page?: number;
  page_size?: number;
}): Promise<SignageHistoryListResponse> =>
  api.get(`/signages/${id}/history`, { params }).then((r) => r.data);

export const getSignagePhotos = (id: number): Promise<SignagePhoto[]> =>
  api.get(`/signages/${id}/photos`).then((r) => r.data);

export const createSignagePhoto = (id: number, data: {
  photo_type: string;
  caption?: string;
}): Promise<SignagePhoto> =>
  api.post(`/signages/${id}/photos`, data).then((r) => r.data);

export const getFloorPlanList = (params?: {
  campus?: string;
  building?: string;
  // [修复 2026-09-05] 新增平面类别过滤（院区平面/楼层平面）
  category?: string;
}): Promise<FloorPlan[]> =>
  api.get('/floor-plans', { params }).then((r) => r.data);

export const getFloorPlan = (id: number): Promise<FloorPlan> =>
  api.get(`/floor-plans/${id}`).then((r) => r.data);

export const createFloorPlan = (data: Partial<FloorPlan>): Promise<FloorPlan> =>
  api.post('/floor-plans', data).then((r) => r.data);

export const deleteFloorPlan = (id: number): Promise<void> =>
  api.delete(`/floor-plans/${id}`).then((r) => r.data);

export const getFloorPlanPoints = (planId: number): Promise<SignagePoint[]> =>
  api.get(`/floor-plans/${planId}/points`).then((r) => r.data);

export const createFloorPlanPoint = (planId: number, data: {
  signage_id: number;
  x_percent: number;
  y_percent: number;
  pin_icon?: string;
  pin_color?: string;
}, excludePointId?: number): Promise<SignagePoint> =>
  // [修复 2026-09-05] 重新绑定时豁免旧点位的重复校验（先建新、后删旧）
  api.post(`/floor-plans/${planId}/points`, data, {
    params: excludePointId ? { exclude_point_id: excludePointId } : undefined,
  }).then((r) => r.data);

export const deleteFloorPlanPoint = (pointId: number): Promise<void> =>
  api.delete(`/floor-plans/points/${pointId}`).then((r) => r.data);

// [修复 2026-09-03] 添加平面图图片上传函数
// [修复 2026-09-03] 移除手动设置的 Content-Type，让 axios 自动设置带 boundary 的 multipart/form-data，
// 避免服务器无法解析 multipart body 导致 ERR_CONNECTION_RESET
export const uploadFloorPlanImage = (planId: number, file: File): Promise<FloorPlan> => {
  const formData = new FormData();
  formData.append('file', file);
  return uploadApi.post(`/floor-plans/${planId}/upload`, formData).then((r) => r.data);
};

// [修复 2026-09-03] 添加更新平面图信息函数
export const updateFloorPlan = (planId: number, data: Partial<FloorPlan>): Promise<FloorPlan> =>
  api.put(`/floor-plans/${planId}/image`, data).then((r) => r.data);

// [修复 2026-09-03] 添加标识照片上传函数
// [修复 2026-09-03] 移除手动设置的 Content-Type，让 axios 自动设置带 boundary 的 multipart/form-data，
// 避免服务器无法解析 multipart body 导致 ERR_CONNECTION_RESET
export const uploadSignagePhoto = (signageId: number, file: File, photoType: 'design' | 'installation' = 'design'): Promise<{
  message: string;
  file_path: string;
  photo_type: string;
}> => {
  const formData = new FormData();
  formData.append('file', file);
  return uploadApi.post(`/signages/${signageId}/upload?photo_type=${photoType}`, formData).then((r) => r.data);
};
