// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

export interface StaffCard {
  id: number;
  entity_type: 'doctor' | 'nurse' | 'technician' | 'admin';
  entity_id: string;
  card_photo: string;
  status: 'pending' | 'confirmed' | 'rejected';
  uploaded_by: string;
  uploaded_at: string;
  confirmed_by: string | null;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
  reject_reason: string | null;
  // [改进] 当前登录用户是否可确认/拒绝该卡片（后端计算返回，用于渲染确认/拒绝按钮）
  can_confirm?: boolean;
}

export interface StaffCardListResponse {
  total: number;
  items: StaffCard[];
  page: number;
  page_size: number;
}
