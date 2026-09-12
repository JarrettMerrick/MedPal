import api from './client';
import type {
  Campus, Building, Floor, Area,
  CampusCreate, CampusUpdate,
  BuildingCreate, BuildingUpdate,
  FloorCreate, FloorUpdate,
  AreaCreate, AreaUpdate,
  CampusTreeNode,
  PaginatedResponse,
} from '../types/campus';

// [修复 2026-09-03] 院区-楼栋-楼层-区域 API 接口
export const campusApi = {
  // ==================== 院区接口 ====================
  
  // 获取院区列表
  getCampuses: async (page: number = 1, pageSize: number = 20, search?: string): Promise<PaginatedResponse<Campus>> => {
    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('page_size', pageSize.toString());
    if (search) params.append('search', search);
    
    const response = await api.get(`campus?${params.toString()}`);
    return response.data;
  },

  // 获取所有启用的院区
  getAllCampuses: async () => {
    const response = await api.get('campus/all');
    return response.data;
  },

  // 获取院区树形结构
  getCampusTree: async (): Promise<CampusTreeNode[]> => {
    const response = await api.get('campus/tree');
    return response.data;
  },

  // 获取院区详情
  getCampus: async (id: number): Promise<Campus> => {
    const response = await api.get(`campus/${id}`);
    return response.data;
  },

  // 创建院区
  createCampus: async (data: CampusCreate): Promise<Campus> => {
    const response = await api.post('campus', data);
    return response.data;
  },

  // 更新院区
  updateCampus: async (id: number, data: CampusUpdate): Promise<Campus> => {
    const response = await api.put(`campus/${id}`, data);
    return response.data;
  },

  // 删除院区
  deleteCampus: async (id: number) => {
    const response = await api.delete(`campus/${id}`);
    return response.data;
  },

  // ==================== 楼栋接口 ====================
  
  // 获取院区下的楼栋列表
  getBuildings: async (campusId: number, page: number = 1, pageSize: number = 20, search?: string): Promise<PaginatedResponse<Building>> => {
    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('page_size', pageSize.toString());
    if (search) params.append('search', search);
    
    const response = await api.get(`campus/${campusId}/buildings?${params.toString()}`);
    return response.data;
  },

  // 获取楼栋详情
  getBuilding: async (id: number): Promise<Building> => {
    const response = await api.get(`campus/buildings/${id}`);
    return response.data;
  },

  // 创建楼栋
  createBuilding: async (data: BuildingCreate): Promise<Building> => {
    const response = await api.post('campus/buildings', data);
    return response.data;
  },

  // 更新楼栋
  updateBuilding: async (id: number, data: BuildingUpdate): Promise<Building> => {
    const response = await api.put(`campus/buildings/${id}`, data);
    return response.data;
  },

  // 删除楼栋
  deleteBuilding: async (id: number) => {
    const response = await api.delete(`campus/buildings/${id}`);
    return response.data;
  },

  // ==================== 楼层接口 ====================
  
  // 获取楼栋下的楼层列表
  getFloors: async (buildingId: number, page: number = 1, pageSize: number = 20): Promise<PaginatedResponse<Floor>> => {
    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('page_size', pageSize.toString());
    
    const response = await api.get(`campus/buildings/${buildingId}/floors?${params.toString()}`);
    return response.data;
  },

  // 获取楼层详情
  getFloor: async (id: number): Promise<Floor> => {
    const response = await api.get(`campus/floors/${id}`);
    return response.data;
  },

  // 创建楼层
  createFloor: async (data: FloorCreate): Promise<Floor> => {
    const response = await api.post('campus/floors', data);
    return response.data;
  },

  // 更新楼层
  updateFloor: async (id: number, data: FloorUpdate): Promise<Floor> => {
    const response = await api.put(`campus/floors/${id}`, data);
    return response.data;
  },

  // 删除楼层
  deleteFloor: async (id: number) => {
    const response = await api.delete(`campus/floors/${id}`);
    return response.data;
  },

  // ==================== 区域接口 ====================
  
  // 获取楼层下的区域列表
  getAreas: async (floorId: number, page: number = 1, pageSize: number = 20): Promise<PaginatedResponse<Area>> => {
    const params = new URLSearchParams();
    params.append('page', page.toString());
    params.append('page_size', pageSize.toString());
    
    const response = await api.get(`campus/floors/${floorId}/areas?${params.toString()}`);
    return response.data;
  },

  // 获取区域详情
  getArea: async (id: number): Promise<Area> => {
    const response = await api.get(`campus/areas/${id}`);
    return response.data;
  },

  // 创建区域
  createArea: async (data: AreaCreate): Promise<Area> => {
    const response = await api.post('campus/areas', data);
    return response.data;
  },

  // 更新区域
  updateArea: async (id: number, data: AreaUpdate): Promise<Area> => {
    const response = await api.put(`campus/areas/${id}`, data);
    return response.data;
  },

  // 删除区域
  deleteArea: async (id: number) => {
    const response = await api.delete(`campus/areas/${id}`);
    return response.data;
  },
};