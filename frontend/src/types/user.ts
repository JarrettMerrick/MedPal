// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

export interface UserInfo {
  employee_id: string;
  name: string;
  role: string;
  department: string | null;
  user_type: string;
  must_change_password: boolean;
  permissions: string[];
  managed_departments: string[];
  work_type_scope: string;
  // [改进] 角色科室数据范围: "all"=全部科室, "managed"=管辖科室, "own"=仅本科室
  // 前端用于科室名称/分类编辑权限判断，与后端 /api/auth/me 返回对齐
  department_scope: string;
  // [新增] 当前登录用户是否有关联的员工记录。为 true 时「个人信息」卡片跳转员工详情页；
  // 为 false（如纯管理员）则跳转个人资料页，并避免发起 getStaff 探测请求造成 404 噪音。
  has_staff_record?: boolean;
  // [新增 2026-09-17] 注册审核状态：
  //   pending  = 待审核（自助注册后）：可登录，但仅能查看/修改个人信息；
  //   approved = 已通过：按角色获得完整权限（管理员建号 / 存量账号均为该值）；
  //   rejected = 已驳回：禁止登录（仅用于状态提示）。
  review_status?: 'pending' | 'approved' | 'rejected';
}

export interface UserItem {
  employee_id: string;
  name: string;
  role: string;
  department: string | null;
  user_type: string;
  is_active: boolean;
  must_change_password: boolean;
  // [新增 2026-09-10] 是否为「系统中最后一个超级管理员」：
  // 为 true 时不允许删除/禁用/角色降级（系统须始终保留至少一个超级管理员）
  is_last_super_admin?: boolean;
}

export interface UserListResponse {
  total: number;
  items: UserItem[];
  page: number;
  page_size: number;
}

export interface LoginResponse {
  access_token: string;
  /**
   * [修复/问题3] refresh_token 现由后端以 HttpOnly Cookie 下发，响应体不再返回，
   * 仅保留可选声明以兼容旧代码。
   */
  refresh_token?: string;
  file_token: string;
  token_type: string;
  user: UserInfo;
}
