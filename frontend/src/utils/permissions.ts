// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import type { UserInfo } from '../types/user';

// ==================== 权限名称常量（新版统一权限） ====================
// 人员管理
export const PERM_STAFF_VIEW = 'staff.view';
export const PERM_STAFF_CREATE = 'staff.create';
export const PERM_STAFF_EDIT = 'staff.edit';
export const PERM_STAFF_DELETE = 'staff.delete';
export const PERM_STAFF_STATUS = 'staff.status';
// [新增 2026-09-11] 人员信息变更审核（立即生效 + 追认/回滚）
// 科室管理员默认拥有（仅限管辖科室的科室级变更）；超级管理员审全部
export const PERM_STAFF_APPROVE = 'staff.approve';
// 科室管理
export const PERM_DEPT_VIEW = 'department.view';
export const PERM_DEPT_CREATE = 'department.create';
export const PERM_DEPT_EDIT = 'department.edit';
export const PERM_DEPT_DELETE = 'department.delete';
// 制度管理
export const PERM_REGULATION_VIEW = 'regulation.view';
export const PERM_REGULATION_CREATE = 'regulation.create';
export const PERM_REGULATION_EDIT = 'regulation.edit';
export const PERM_REGULATION_DELETE = 'regulation.delete';
// 标识管理
// [修复 2026-09-07] 权限细化：拆分为「标识平面」与「标识设置」两大分类下的细粒度权限项
export const PERM_SIGNAGE_VIEW = 'signage.view';
export const PERM_SIGNAGE_CREATE = 'signage.create';
export const PERM_SIGNAGE_EDIT = 'signage.edit';
export const PERM_SIGNAGE_DELETE = 'signage.delete';
export const PERM_SIGNAGE_EXPORT = 'signage.export';
export const PERM_SIGNAGE_FLOORPLAN = 'signage.floorplan';
// 标识平面（workspace）
export const PERM_SIGNAGE_MARKER = 'signage.marker';          // 标识标记（平面图点位增删）
export const PERM_SIGNAGE_ALERT = 'signage.alert';            // 查看标识预警
export const PERM_SIGNAGE_INSPECTION = 'signage.inspection';  // 标识巡检（提交巡检结果/照片）
export const PERM_SIGNAGE_REPAIR = 'signage.repair';          // 维修记录（查看全部维修记录并按条件导出）
// 标识设置（settings）
export const PERM_SIGNAGE_CAMPUS = 'signage.campus';          // 院区管理
export const PERM_SIGNAGE_CATEGORY = 'signage.category';      // 标识分类设置
export const PERM_SIGNAGE_SUPPLIER = 'signage.supplier';      // 供应商设置
// 用户管理
export const PERM_USER_VIEW = 'user.view';
export const PERM_USER_CREATE = 'user.create';
export const PERM_USER_EDIT = 'user.edit';
export const PERM_USER_DELETE = 'user.delete';
export const PERM_USER_RESET_PWD = 'user.reset_password';
// [新增 2026-09-10] 账号审核：审核登录页自助注册申请（科室管理员仅限管辖科室）
export const PERM_USER_APPROVE = 'user.approve';
// 角色管理
export const PERM_ROLE_VIEW = 'role.view';
export const PERM_ROLE_CREATE = 'role.create';
export const PERM_ROLE_EDIT = 'role.edit';
export const PERM_ROLE_DELETE = 'role.delete';
// 数据管理
export const PERM_DATA_EXPORT = 'data.export';
export const PERM_DATA_IMPORT = 'data.import';
// 系统管理
export const PERM_SYSTEM_CONFIG = 'system.config';
export const PERM_SYSTEM_BACKUP = 'system.backup';
export const PERM_SYSTEM_AUDIT = 'system.audit';
// 特殊功能
export const PERM_CARD_UPLOAD = 'card.upload';
export const PERM_STAFF_VIEW_RESIGNED = 'staff.view_resigned';
// [新增 2026-09-11] 站内信
export const PERM_MESSAGE_VIEW = 'message.view';
export const PERM_MESSAGE_SEND = 'message.send';
export const PERM_MESSAGE_BROADCAST = 'message.broadcast';

/**
 * 检查用户是否有指定权限（基于服务端返回的 permissions 数组，不再硬编码角色名绕过）
 */
export function hasPermission(user: UserInfo | null, permissionName: string): boolean {
  if (!user) return false;
  return user.permissions?.includes(permissionName) ?? false;
}

/**
 * 检查用户是否拥有任意一个指定权限
 */
export function hasAnyPermission(user: UserInfo | null, ...permissionNames: string[]): boolean {
  if (!user) return false;
  return permissionNames.some((name) => hasPermission(user, name));
}

/**
 * 检查用户是否拥有指定角色或指定权限（兼容自定义角色）
 */
export function hasRoleOrPermission(user: UserInfo | null, roles: string[], ...permissionNames: string[]): boolean {
  if (!user) return false;
  if (roles.includes(user.role)) return true;
  return hasAnyPermission(user, ...permissionNames);
}
