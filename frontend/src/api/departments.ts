// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import api from './client';
import type { Department, DepartmentListResponse, SpecialtyImage, EquipmentImage } from '../types/department';

export const getDepartments = (params: { page?: number; page_size?: number; search?: string }) =>
  api.get<DepartmentListResponse>('/departments', { params }).then((r) => r.data);

// [修复 2026-09-01] 返回类型添加 allowed_work_types 字段，支持混合科室配置
export const getAllDepartments = () =>
  api.get<{ id: number; name: string; category: string; allowed_work_types: string | null }[]>('/departments/all').then((r) => r.data);

export const getDepartmentsByCategory = (category: string) =>
  api.get<{ id: number; name: string; category: string; allowed_work_types: string | null }[]>('/departments/all', { params: { category } }).then((r) => r.data);

export const getDepartment = (id: number) =>
  api.get<Department>(`/departments/${id}`).then((r) => r.data);

// [修复 2026-09-01] 参数添加 allowed_work_types 字段，支持混合科室配置
export const createDepartment = (data: { 
  name: string; 
  description?: string; 
  category?: string;
  allowed_work_types?: string | null;
  specialties?: { name: string; detail?: string; sort_order?: number }[];
  equipments?: { name: string; model?: string; function_description?: string; features?: string; sort_order?: number }[];
}) =>
  api.post<Department>('/departments', data).then((r) => r.data);

export const updateDepartment = (id: number, data: { 
  name?: string; 
  description?: string; 
  category?: string;
  allowed_work_types?: string | null;
  specialties?: { id?: number; name: string; detail?: string; sort_order?: number }[];
  equipments?: { id?: number; name: string; model?: string; function_description?: string; features?: string; sort_order?: number }[];
}) =>
  api.put<Department>(`/departments/${id}`, data).then((r) => r.data);

export const deleteDepartment = (id: number) =>
  api.delete(`/departments/${id}`).then((r) => r.data);

export const getDepartmentStaffStats = (id: number) =>
  api.get<{ category: string; titles: Record<string, number>; total: number }>(`/departments/${id}/staff-stats`).then((r) => r.data);

export const uploadSpecialtyImage = (departmentId: number, specialtyId: number, file: File, caption: string) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('caption', caption);
  return api.post<SpecialtyImage>(`/departments/${departmentId}/specialties/${specialtyId}/images`, formData).then((r) => r.data);
};

export const deleteSpecialtyImage = (departmentId: number, specialtyId: number, imageId: number) =>
  api.delete(`/departments/${departmentId}/specialties/${specialtyId}/images/${imageId}`).then((r) => r.data);

export const updateSpecialtyImageCaption = (departmentId: number, specialtyId: number, imageId: number, caption: string) =>
  api.put<SpecialtyImage>(`/departments/${departmentId}/specialties/${specialtyId}/images/${imageId}`, { caption }).then((r) => r.data);

// 设备图片相关API
export const uploadEquipmentImage = (departmentId: number, equipmentId: number, file: File, caption: string) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('caption', caption);
  return api.post<EquipmentImage>(`/departments/${departmentId}/equipments/${equipmentId}/images`, formData).then((r) => r.data);
};

export const deleteEquipmentImage = (departmentId: number, equipmentId: number, imageId: number) =>
  api.delete(`/departments/${departmentId}/equipments/${equipmentId}/images/${imageId}`).then((r) => r.data);

export const updateEquipmentImageCaption = (departmentId: number, equipmentId: number, imageId: number, caption: string) =>
  api.put<EquipmentImage>(`/departments/${departmentId}/equipments/${equipmentId}/images/${imageId}`, { caption }).then((r) => r.data);

// 科室合照相关API
export const uploadGroupPhoto = (departmentId: number, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post<{ group_photo: string; message: string }>(`/departments/${departmentId}/group-photo`, formData).then((r) => r.data);
};

export const deleteGroupPhoto = (departmentId: number) =>
  api.delete(`/departments/${departmentId}/group-photo`).then((r) => r.data);
