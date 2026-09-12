// [修复 2026-09-04] 标识设置相关的API接口
import api from './client';

// [修复 2026-09-04] 标识分类数据接口
export interface SignageCategory {
  id: number;
  name: string;
  code: string;
  description?: string;
  // [修复 2026-09-05] 新增 color 分类颜色（十六进制，用于标记点位着色）
  color?: string;
  // [修复 2026-09-05] 新增 shape 标记形状（circle/square/triangle/diamond/star/hydrant），与颜色组合渲染在标识平面图上
  shape?: string;
  // [新增 2026-09-05] 巡检周期（天）：用于巡检到期/超期预警；留空表示该分类不参与巡检预警
  inspection_cycle_days?: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// [修复 2026-09-04] 供应商数据接口
export interface Supplier {
  id: number;
  name: string;
  type: 'manufacturer'; // manufacturer: 制作厂商
  contact_person?: string;
  phone?: string;
  address?: string;
  email?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// [修复 2026-09-04] 获取标识分类列表
export const getSignageCategories = async (params?: {
  page?: number;
  page_size?: number;
  search?: string;
  is_active?: boolean;
}): Promise<{ total: number; items: SignageCategory[] }> => {
  try {
    const response = await api.get('/signage-categories', { params });
    return response.data;
  } catch (error) {
    console.error('获取标识分类列表失败:', error);
    // 返回模拟数据供前端开发使用
    return {
      total: 5,
      items: [
        { id: 1, name: '科室牌', code: 'DEPT_SIGN', description: '科室名称标牌', color: '#0E7F8A', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
        { id: 2, name: '楼层索引', code: 'FLOOR_INDEX', description: '楼层导向标牌', color: '#4263EB', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
        { id: 3, name: '功能区域', code: 'FUNC_AREA', description: '功能区域标识', color: '#37B24D', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
        { id: 4, name: '安全标识', code: 'SAFETY_SIGN', description: '安全警示标识', color: '#E03131', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
        { id: 5, name: '导向标识', code: 'GUIDE_SIGN', description: '导向指引标识', color: '#F76707', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
      ],
    };
  }
};

// [修复 2026-09-04] 创建标识分类
export const createSignageCategory = async (data: Omit<SignageCategory, 'id' | 'created_at' | 'updated_at'>): Promise<SignageCategory> => {
  try {
    const response = await api.post('/signage-categories', data);
    return response.data;
  } catch (error) {
    console.error('创建标识分类失败:', error);
    throw error;
  }
};

// [修复 2026-09-04] 更新标识分类
export const updateSignageCategory = async (id: number, data: Partial<SignageCategory>): Promise<SignageCategory> => {
  try {
    const response = await api.put(`/signage-categories/${id}`, data);
    return response.data;
  } catch (error) {
    console.error('更新标识分类失败:', error);
    throw error;
  }
};

// [修复 2026-09-04] 删除标识分类
export const deleteSignageCategory = async (id: number): Promise<void> => {
  try {
    await api.delete(`/signage-categories/${id}`);
  } catch (error) {
    console.error('删除标识分类失败:', error);
    throw error;
  }
};

// [修复 2026-09-04] 获取供应商列表
export const getSuppliers = async (params?: {
  page?: number;
  page_size?: number;
  search?: string;
  is_active?: boolean;
}): Promise<{ total: number; items: Supplier[] }> => {
  try {
    const response = await api.get('/suppliers', { params });
    return response.data;
  } catch (error) {
    console.error('获取供应商列表失败:', error);
    // 返回模拟数据供前端开发使用
    return {
      total: 3,
      items: [
        { id: 1, name: '示例标识制作有限公司', type: 'manufacturer', contact_person: '张经理', phone: '13800138001', address: '上海市浦东新区', email: 'zhang@example.com', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
        { id: 2, name: '医疗标识厂', type: 'manufacturer', contact_person: '李经理', phone: '13800138002', address: '上海市徐汇区', email: 'li@example.com', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
        { id: 3, name: '健康标识有限公司', type: 'manufacturer', contact_person: '王经理', phone: '13800138003', address: '上海市静安区', email: 'wang@example.com', is_active: true, created_at: '2026-09-04', updated_at: '2026-09-04' },
      ],
    };
  }
};

// [修复 2026-09-04] 创建供应商
export const createSupplier = async (data: Omit<Supplier, 'id' | 'created_at' | 'updated_at'>): Promise<Supplier> => {
  try {
    const response = await api.post('/suppliers', data);
    return response.data;
  } catch (error) {
    console.error('创建供应商失败:', error);
    throw error;
  }
};

// [修复 2026-09-04] 更新供应商
export const updateSupplier = async (id: number, data: Partial<Supplier>): Promise<Supplier> => {
  try {
    const response = await api.put(`/suppliers/${id}`, data);
    return response.data;
  } catch (error) {
    console.error('更新供应商失败:', error);
    throw error;
  }
};

// [修复 2026-09-04] 删除供应商
export const deleteSupplier = async (id: number): Promise<void> => {
  try {
    await api.delete(`/suppliers/${id}`);
  } catch (error) {
    console.error('删除供应商失败:', error);
    throw error;
  }
};

// [修复 2026-09-04] 获取启用的标识分类列表（用于下拉选择）
export const getActiveSignageCategories = async (): Promise<SignageCategory[]> => {
  try {
    const response = await api.get('/signage-categories/active');
    return response.data;
  } catch (error) {
    console.error('获取启用的标识分类列表失败:', error);
    // 返回模拟数据
    return [
      { id: 1, name: '科室牌', code: 'DEPT_SIGN', description: '科室名称标牌', color: '#0E7F8A', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
      { id: 2, name: '楼层索引', code: 'FLOOR_INDEX', description: '楼层导向标牌', color: '#4263EB', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
      { id: 3, name: '功能区域', code: 'FUNC_AREA', description: '功能区域标识', color: '#37B24D', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
      { id: 4, name: '安全标识', code: 'SAFETY_SIGN', description: '安全警示标识', color: '#E03131', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
      { id: 5, name: '导向标识', code: 'GUIDE_SIGN', description: '导向指引标识', color: '#F76707', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
    ];
  }
};

// [修复 2026-09-04] 获取启用的供应商列表（用于下拉选择）
export const getActiveSuppliers = async (): Promise<Supplier[]> => {
  try {
    const response = await api.get('/suppliers/active', { params: { type: 'manufacturer' } });
    return response.data;
  } catch (error) {
    console.error('获取启用的供应商列表失败:', error);
    // 返回模拟数据
    return [
      { id: 1, name: '示例标识制作有限公司', type: 'manufacturer', contact_person: '张经理', phone: '13800138001', address: '上海市浦东新区', email: 'zhang@example.com', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
      { id: 2, name: '医疗标识厂', type: 'manufacturer', contact_person: '李经理', phone: '13800138002', address: '上海市徐汇区', email: 'li@example.com', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
      { id: 3, name: '健康标识有限公司', type: 'manufacturer', contact_person: '王经理', phone: '13800138003', address: '上海市静安区', email: 'wang@example.com', is_active: true, created_at: '2026-09-04T00:00:00', updated_at: '2026-09-04T00:00:00' },
    ];
  }
};
