// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

export interface DepartmentSpecialty {
  id?: number;
  name: string;
  detail: string;
  sort_order: number;
  images?: SpecialtyImage[];
}

export interface SpecialtyImage {
  id: number;
  specialty_id: number;
  image_url: string;
  caption: string | null;
  sort_order: number;
}

export interface DepartmentEquipment {
  id?: number;
  name: string;
  model: string;
  function_description: string;
  features: string;
  sort_order: number;
  images?: EquipmentImage[];
}

export interface EquipmentImage {
  id: number;
  equipment_id: number;
  image_url: string;
  caption: string | null;
  sort_order: number;
}

export interface Department {
  id: number;
  name: string;
  category: string;
  description: string;
  group_photo: string | null;
  // [修复 2026-09-01] 新增 allowed_work_types 字段，支持混合科室配置
  allowed_work_types: string | null;
  specialties: DepartmentSpecialty[];
  equipments: DepartmentEquipment[];
  updated_by: string | null;
  updated_at: string | null;
}

export interface DepartmentListItem {
  id: number;
  name: string;
}

export interface DepartmentListResponse {
  items: Department[];
  total: number;
}
