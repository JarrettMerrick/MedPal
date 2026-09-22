// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
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
// [新增 2026-09-15] 照片上传：控制能否上传人员形象照（正面/侧面）。
// 本人上传自己的照片始终允许（基础能力，不校验本权限）；
// 为他人上传需本权限且在其科室/工种数据范围内；
// 删除照片仍由 PERM_STAFF_EDIT（修改人员信息）控制。
export const PERM_STAFF_PHOTO_UPLOAD = 'staff.photo_upload';
// [新增 2026-09-15] 修改历史（人员）：人员详情页「修改历史」入口与 /api/audit/history 接口访问；
// 默认仅超级管理员拥有，可在「角色管理 → 人员管理」中按角色授予/回收。
export const PERM_STAFF_VIEW_HISTORY = 'staff.view_history';
// 科室管理
export const PERM_DEPT_VIEW = 'department.view';
export const PERM_DEPT_CREATE = 'department.create';
export const PERM_DEPT_EDIT = 'department.edit';
export const PERM_DEPT_DELETE = 'department.delete';
// [新增 2026-09-15] 修改历史（科室）：科室详情页「修改历史」入口与 /api/audit/history 接口访问；
// 默认仅超级管理员拥有，可在「角色管理 → 科室管理」中按角色授予/回收。
export const PERM_DEPT_VIEW_HISTORY = 'department.view_history';
// 制度管理
export const PERM_REGULATION_VIEW = 'regulation.view';
export const PERM_REGULATION_CREATE = 'regulation.create';
export const PERM_REGULATION_EDIT = 'regulation.edit';
export const PERM_REGULATION_DELETE = 'regulation.delete';
// 标识管理
// [修复 2026-09-07] 权限细化：拆分为「标识平面」与「标识设置」两大分类下的细粒度权限项
export const PERM_SIGNAGE_VIEW = 'signage.view';
// [新增 2026-09-18] 标识总览：独立权限点，默认仅科室管理员与超级管理员拥有（普通员工不可见）
export const PERM_SIGNAGE_OVERVIEW = 'signage.overview';
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
// [新增 2026-09-17] 文件库（设计文件集中管理：分类 / 标签 / 版本 / 回收站 / 标准设计文件）
export const PERM_FILE_VIEW = 'file.view';                    // 浏览 / 预览 / 下载
export const PERM_FILE_UPLOAD = 'file.upload';                // 上传文件
export const PERM_FILE_EDIT = 'file.edit';                    // 改名 / 分类 / 标签 / 标准标记 / 分类与标签维护
export const PERM_FILE_DELETE = 'file.delete';                // 删除（含批量、回收站与彻底删除）
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
// [新增 2026-09-14] 功能级权限点：控制该角色能否访问对应功能。
// 与「系统设置 → 功能开关」构成两层控制，两者都通过才放行；
// 功能内部的具体操作仍由上面的细粒度权限（message.send / signage.create 等）控制。
// [调整 2026-09-14] 所有功能开关权限合并为**单一**权限点「功能开关」：
// 一个角色要么可访问全部受开关管控的模块，要么全部不可访问；
// 各模块的单位级启停仍由「系统设置 → 功能开关」分别控制。
export const PERM_FEATURE_ACCESS = 'feature.access';
// [新增 2026-09-15] 通知设置：控制角色能否访问「系统设置 → 通知设置」
// （配置系统站内信的事件开关 / 文案模板 / 收件人范围）。
// 与 PERM_FEATURE_ACCESS 同属角色管理中的「系统设置」分类；
// 此前通知设置复用 system.config，现已拆分为独立权限项，可单独授权。
export const PERM_FEATURE_NOTIFICATION = 'feature.notification';

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
