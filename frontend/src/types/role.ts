// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

export interface Permission {
  id: number;
  name: string;
  display_name: string;
  category: string;
  description: string | null;
}

export interface Role {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  is_system: boolean;
  department_scope: string;   // own / managed / all
  work_type_scope: string;     // all 或 "doctor,nurse" 等
  permissions: Permission[];
  created_at: string | null;
  updated_at: string | null;
}

export interface RoleListResponse {
  total: number;
  items: Role[];
  page: number;
  page_size: number;
}

export interface PermissionCategory {
  category: string;
  category_label: string;
  permissions: Permission[];
}

export interface RoleOption {
  id: number;
  name: string;
  display_name: string;
}
