// [修复 2026-09-03] 院区-楼栋-楼层-区域 类型定义

// ==================== 院区 ====================
export interface Campus {
  id: number;
  name: string;
  description?: string;
  address?: string;
  code?: string;
  is_active: boolean;
  created_by?: string;
  created_at?: string;
  updated_by?: string;
  updated_at?: string;
  building_count: number;
}

export interface CampusCreate {
  name: string;
  description?: string;
  address?: string;
  code?: string;
  is_active?: boolean;
}

export interface CampusUpdate {
  name?: string;
  description?: string;
  address?: string;
  code?: string;
  is_active?: boolean;
}

// ==================== 楼栋 ====================
export interface Building {
  id: number;
  campus_id: number;
  name: string;
  building_number: string;
  description?: string;
  is_active: boolean;
  campus_name?: string;
  created_by?: string;
  created_at?: string;
  updated_by?: string;
  updated_at?: string;
  floor_count: number;
}

export interface BuildingCreate {
  campus_id: number;
  name: string;
  building_number: string;
  description?: string;
  is_active?: boolean;
}

export interface BuildingUpdate {
  campus_id?: number;
  name?: string;
  building_number?: string;
  description?: string;
  is_active?: boolean;
}

// ==================== 楼层 ====================
export interface Floor {
  id: number;
  building_id: number;
  /** [调整 2026-09-17] 楼层号改为字母编号：F1/F2…（地上）、B1/B2…（地下，B1 = 地下一层） */
  floor_number: string;
  floor_name?: string;
  description?: string;
  is_active: boolean;
  building_name?: string;
  campus_id?: number;
  campus_name?: string;
  created_by?: string;
  created_at?: string;
  updated_by?: string;
  updated_at?: string;
  area_count: number;
}

export interface FloorCreate {
  building_id: number;
  /** [调整 2026-09-17] 楼层号改为字母编号：F1/F2…（地上）、B1/B2…（地下，B1 = 地下一层） */
  floor_number: string;
  floor_name?: string;
  description?: string;
  is_active?: boolean;
}

export interface FloorUpdate {
  building_id?: number;
  floor_number?: number;
  floor_name?: string;
  description?: string;
  is_active?: boolean;
}

// ==================== 区域 ====================
export interface Area {
  id: number;
  floor_id: number;
  name: string;
  area_type: 'east' | 'west' | 'merged';
  description?: string;
  is_active: boolean;
  floor_name?: string;
  building_id?: number;
  building_name?: string;
  campus_id?: number;
  campus_name?: string;
  created_by?: string;
  created_at?: string;
  updated_by?: string;
  updated_at?: string;
}

export interface AreaCreate {
  floor_id: number;
  name: string;
  area_type: 'east' | 'west' | 'merged';
  description?: string;
  is_active?: boolean;
}

export interface AreaUpdate {
  floor_id?: number;
  name?: string;
  area_type?: 'east' | 'west' | 'merged';
  description?: string;
  is_active?: boolean;
}

// ==================== 树形结构 ====================
export interface CampusTreeNode {
  id: number;
  name: string;
  children: BuildingTreeNode[];
}

export interface BuildingTreeNode {
  id: number;
  name: string;
  building_number: string;
  children: FloorTreeNode[];
}

export interface FloorTreeNode {
  id: number;
  /** [调整 2026-09-17] 楼层号改为字母编号：F1/F2…（地上）、B1/B2…（地下，B1 = 地下一层） */
  floor_number: string;
  floor_name?: string;
  children: AreaTreeNode[];
}

export interface AreaTreeNode {
  id: number;
  name: string;
  area_type: string;
}

// ==================== 分页响应 ====================
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}