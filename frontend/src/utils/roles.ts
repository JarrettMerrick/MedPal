// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

// 角色常量（3个角色）
export const ROLE_SUPER_ADMIN = 'admin_manager';  // 超级管理员=系统管理员
export const ROLE_ADMIN_MANAGER = 'admin_manager';
export const ROLE_DEPT_MANAGER = 'dept_manager';
export const ROLE_EMPLOYEE = 'employee';

// 角色中文名映射
export const ROLE_LABELS: Record<string, string> = {
  admin_manager: '超级管理员',
  dept_manager: '科室管理员',
  employee: '普通员工',
};

// 角色显示色
export const ROLE_COLORS: Record<string, string> = {
  admin_manager: 'bg-red-50 text-red-600',
  dept_manager: 'bg-[#ED7B2F]/10 text-[#ED7B2F]',
  employee: 'bg-gray-100 text-gray-600',
};

export function getRoleLabel(role: string): string {
  return ROLE_LABELS[role] || role;
}

export function getRoleColor(role: string): string {
  return ROLE_COLORS[role] || 'bg-gray-100 text-gray-600';
}
