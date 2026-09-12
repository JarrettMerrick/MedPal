// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import React from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { hasAnyPermission } from '../utils/permissions';

/**
 * 路由级权限守卫：无权限用户访问时重定向到首页。
 * [修复] 新增 allowSelf 支持：编辑自己的记录时放行（如 /staff/edit/:id），
 * 使「员工本人可编辑自己」的业务规则与权限点校验并存，避免仅靠页面内按钮隐藏。
 */
const RoleGuard: React.FC<{
  children: React.ReactNode;
  permissions?: string[];
  allowSelf?: boolean;
}> = ({ children, permissions, allowSelf = false }) => {
  const { user, isLoading } = useAuth();
  const params = useParams();
  if (isLoading) {
    return null;
  }
  if (!user) {
    return <Navigate to="/dashboard" replace />;
  }
  // 本人编辑自己的记录：允许（与后端 update_staff_endpoint 的隐式权限一致）
  const isSelf = allowSelf && params.id != null && user.employee_id === params.id;
  if (permissions && permissions.length > 0 && (isSelf || hasAnyPermission(user, ...permissions))) {
    return <>{children}</>;
  }
  return <Navigate to="/dashboard" replace />;
};

export default RoleGuard;
