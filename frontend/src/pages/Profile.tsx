// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 个人信息页面，员工可在此维护个人基本信息和专业介绍。
 * 字段包括：姓名、科室、专业擅长、社会任职、荣誉、备注等。
 * 提交后同步更新 AuthContext 中的用户信息。
 *
 * 改造说明（v1.1.0）：
 * - [改进] 手写 form/input/select/textarea → Ant Design Form 声明式表单
 * - [改进] 手写返回按钮 → Button + LeftOutlined
 * - [改进] alert → message.success/error
 * - 业务逻辑不变：API 调用、部门加载、上下文更新
 *
 * [调整 2026-09-11] 个人信息修改纳入「立即生效 + 追认审核」：
 * - 修改后立即生效（页面立刻显示最新值），并在显著位置提示「XX 未审核」；
 * - 姓名/科室 → 超级管理员审核；学历/职称/职务 → 科室负责人审核（本页暂未开放这几项）；
 * - 备注/擅长/社会任职/荣誉 → 免审直接生效；
 * - 本页新增「我的提交」区块：可查看审核进度，待审变更可自行撤回（撤回即回滚）。
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
// [新增 2026-09-17] 待审核账号的显著提示使用 Alert
import { Form, Input, Select, Button, Card, Typography, App, Table, Tag, Space, Tooltip, Alert } from 'antd';
import { UndoOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useAuth } from '../contexts/AuthContext';
import { updateProfile, getMe } from '../api/auth';
import { getDepartmentsByCategory } from '../api/departments';
import { getStaff } from '../api/staff';
// [统一时间口径] 时间展示一律走 utils/time
import { formatDateTimeStandard } from '../utils/time';
import {
  cancelStaffChange,
  listMyStaffChanges,
  type StaffChangeItem,
} from '../api/staffChanges';
import StaffChangeNotice from '../components/StaffChangeNotice';
import PageContainer from '../components/PageContainer';
import PageHeader from '../components/PageHeader';
import { getErrorMessage } from '../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

/** 个人资料表单字段类型 */
interface ProfileFormValues {
  name: string;
  department: string;
  expertise_short: string;
  expertise_standard: string;
  social_appointments: string;
  honors: string;
  remarks: string;
}

const CHANGE_STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'gold', label: '待审核' },
  approved: { color: 'green', label: '已通过' },
  rejected: { color: 'red', label: '已驳回' },
  cancelled: { color: 'gray', label: '已撤回' },
};

// [统一时间口径] 原 new Date(value).toLocaleString() 会把后端无时区标记的 UTC 串
// 按浏览器本地时区解释（显示比实际少 8 小时），统一改走 utils/time
const formatTime = (value: string | null): string =>
  value ? formatDateTimeStandard(value) : '--';

const Profile: React.FC = () => {
  const navigate = useNavigate();
  // [新增 2026-09-17] isPendingReview：待审核账号在页面顶部展示提示横幅
  const { user, setUser, isPendingReview } = useAuth();
  const { message, modal } = App.useApp(); // [改进] 使用 App.useApp 获取 message 实例
  const [form] = Form.useForm<ProfileFormValues>();
  const [loading, setLoading] = useState(false);
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);
  // [新增 2026-09-11] 我的变更提交（审核进度 + 撤回）
  const [myChanges, setMyChanges] = useState<StaffChangeItem[]>([]);
  const [changesLoading, setChangesLoading] = useState(false);

  /** 预填 staff 记录中的个人介绍字段（撤回/驳回回滚后需重新拉取） */
  const loadStaffFields = useCallback(() => {
    if (!user) return;
    getStaff(user.employee_id)
      .then((data) => {
        form.setFieldsValue({
          expertise_short: data.expertise_short || '',
          expertise_standard: data.expertise_standard || '',
          social_appointments: data.social_appointments || '',
          honors: data.honors || '',
          remarks: data.remarks || '',
        });
      })
      .catch(() => {});
  }, [user, form]);

  /** 我的提交列表（供审核进度展示与撤回） */
  const loadMyChanges = useCallback(() => {
    if (!user) return;
    setChangesLoading(true);
    listMyStaffChanges({ page: 1, page_size: 20 })
      .then((res) => setMyChanges(res.items))
      .catch(() => setMyChanges([]))
      .finally(() => setChangesLoading(false));
  }, [user]);

  // 初始化表单数据
  useEffect(() => {
    if (user) {
      form.setFieldsValue({
        name: user.name || '',
        department: user.department || '',
      });
      loadStaffFields();
      loadMyChanges();
    }
  }, [user, form, loadStaffFields, loadMyChanges]);

  // 加载科室列表（三级分类合并）
  useEffect(() => {
    getDepartmentsByCategory('临床专科')
      .then((clinical) => {
        getDepartmentsByCategory('护理病区')
          .then((nursing) => {
            getDepartmentsByCategory('行政科室')
              .then((admin) => setDepartments([...clinical, ...nursing, ...admin]))
              .catch(() => setDepartments([...clinical, ...nursing]));
          })
          .catch(() => setDepartments(clinical));
      })
      .catch(() => {});
  }, []);

  // 角色/用户类型映射
  const getRoleName = (role: string) => {
    const roleMap: Record<string, string> = { admin_manager: '超级管理员', dept_manager: '科室管理员', employee: '员工' };
    return roleMap[role] || role;
  };

  const getUserTypeName = (userType: string) => {
    const typeMap: Record<string, string> = { doctor: '医生', nurse: '护士', admin_user: '管理员' };
    return typeMap[userType] || userType;
  };

  /** 提交保存 */
  const handleSubmit = async (values: ProfileFormValues) => {
    setLoading(true);
    try {
      const updated = await updateProfile({
        name: values.name,
        department: values.department || undefined,
        expertise_short: values.expertise_short || undefined,
        expertise_standard: values.expertise_standard || undefined,
        social_appointments: values.social_appointments || undefined,
        honors: values.honors || undefined,
        remarks: values.remarks || undefined,
      });
      if (user) {
        setUser({ ...user, name: updated.name, department: updated.department });
      }
      message.success('保存成功'); // [改进] 替代 alert
      loadMyChanges();
    } catch (err: unknown) {
      message.error(getErrorMessage(err, '操作失败')); // [改进] 替代 alert
    } finally {
      setLoading(false);
    }
  };

  /** [新增 2026-09-11] 撤回待审变更（撤回即回滚为修改前的值） */
  const handleCancelChange = (record: StaffChangeItem) => {
    modal.confirm({
      title: '撤回本次变更？',
      content: (
        <div>
          <div style={{ marginBottom: 6 }}>{record.change_summary}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            撤回后本次修改将回滚为修改前的值。
          </Text>
        </div>
      ),
      okText: '确认撤回',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await cancelStaffChange(record.id);
          message.success('已撤回，相关信息已回滚');
          loadMyChanges();
          loadStaffFields();
          getMe().then(setUser).catch(() => {}); // 姓名可能在回滚范围内，刷新本地用户信息
        } catch (err) {
          message.error(getErrorMessage(err, '撤回失败'));
        }
      },
    });
  };

  const changeColumns: ColumnsType<StaffChangeItem> = [
    {
      title: '变更内容', key: 'summary',
      render: (_, r) => (
        <div style={{ fontSize: 12 }}>
          <div>{r.change_summary || '--'}</div>
          <Space size={4} wrap style={{ marginTop: 4 }}>
            {r.changed_labels.map((l) => <Tag key={l}>{l}</Tag>)}
          </Space>
        </div>
      ),
    },
    {
      title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 160,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: '审核人', key: 'level', width: 110,
      render: (_, r) => <Tag color={r.review_level === 'admin' ? 'purple' : 'blue'}>{r.level_label}</Tag>,
    },
    {
      title: '状态', key: 'status', width: 150,
      render: (_, r) => {
        const meta = CHANGE_STATUS_META[r.status] || { color: 'default', label: r.status };
        return (
          <Space direction="vertical" size={0}>
            <Tag color={meta.color}>{meta.label}</Tag>
            {r.reject_reason && (
              <Text type="danger" style={{ fontSize: 12 }}>原因：{r.reject_reason}</Text>
            )}
            {r.rollback_note && (
              <Text type="warning" style={{ fontSize: 12 }}>{r.rollback_note}</Text>
            )}
          </Space>
        );
      },
    },
    {
      title: '操作', key: 'action', width: 100, fixed: 'right',
      render: (_, r) =>
        r.status === 'pending' ? (
          <Tooltip title="撤回后回滚为修改前的值">
            <Button size="small" icon={<UndoOutlined />} onClick={() => handleCancelChange(r)}>
              撤回
            </Button>
          </Tooltip>
        ) : (
          <Text type="secondary">{r.reviewed_at ? formatTime(r.reviewed_at) : '--'}</Text>
        ),
    },
  ];

  if (!user) return null;

  const pendingChanges = myChanges.filter((c) => c.status === 'pending');

  return (
    <PageContainer maxWidth={720}>
      {/* 标题栏 */}
      <PageHeader title="个人信息" onBack={() => navigate('/dashboard')} />

      {/* [新增 2026-09-17] 待审核账号提示：注册成功已可登录，但审核通过前仅开放
          个人信息相关权限（侧边栏也已精简），此处给出明确说明与后续指引 */}
      {isPendingReview && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="账号正在审核中"
          description="您已成功登录，可在此完善个人资料。审核通过前仅能查看和修改个人信息，审核通过后将自动解锁系统全部功能。"
        />
      )}

      {/* [新增 2026-09-11] 显著位置提示「XX 未审核」（本人的待审变更） */}
      <StaffChangeNotice
        changes={pendingChanges}
        titlePrefix="我的信息"
        onReviewed={() => { loadMyChanges(); loadStaffFields(); }}
      />

      <Card>
        <Form<ProfileFormValues>
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
        >
          {/* 只读字段 */}
          <Form.Item label="工号">
            <Input value={user.employee_id} disabled />
          </Form.Item>

          <Form.Item
            name="name"
            label="姓名"
            rules={[{ required: true, message: '请输入姓名' }]}
            extra="姓名变更需经超级管理员审核"
          >
            <Input placeholder="请输入姓名" />
          </Form.Item>

          <Form.Item name="department" label="所属科室/部门" extra="科室变更需经超级管理员审核（审核通过后生效）">
            <Select placeholder="未分配" allowClear showSearch>
              {departments.map((d) => (
                <Select.Option key={d.id} value={d.name}>{d.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>

          {/* 个人介绍区 */}
          <div style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 16, marginTop: 8 }}>
            <Title level={5} style={{ marginBottom: 16 }}>个人介绍</Title>

            <Form.Item
              name="expertise_short"
              label="专业擅长（短）"
              extra="100 字以内，用于文字排版不能显示太多的地方"
              rules={[{ max: 100, message: '专业擅长（短）不能超过 100 字' }]}
            >
              <TextArea maxLength={100} showCount rows={2} placeholder="如：冠心病介入治疗" />
            </Form.Item>

            <Form.Item name="expertise_standard" label="专业擅长（标准）">
              <TextArea rows={3} placeholder="详细描述专业擅长领域" />
            </Form.Item>

            <Form.Item name="social_appointments" label="社会任职">
              <TextArea rows={4} placeholder="如：XX医学会委员" />
            </Form.Item>

            <Form.Item name="honors" label="获得荣誉">
              <TextArea rows={2} placeholder="如：XX科技进步奖" />
            </Form.Item>

            <Form.Item name="remarks" label="备注">
              <TextArea rows={2} />
            </Form.Item>
          </div>

          {/* 只读角色/用户类型 */}
          <Form.Item label="角色">
            <Input value={getRoleName(user.role)} disabled />
          </Form.Item>

          <Form.Item label="用户类型">
            <Input value={getUserTypeName(user.user_type)} disabled />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>
              保存
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* [新增 2026-09-11] 我的提交：查看审核进度，待审可撤回 */}
      <Card title="我的提交" style={{ marginTop: 16 }} styles={{ body: { padding: 0 } }}>
        <Table<StaffChangeItem>
          rowKey="id"
          size="small"
          columns={changeColumns}
          dataSource={myChanges}
          loading={changesLoading}
          pagination={false}
          // [调整 2026-09-19] 移除固定 scroll={{ x: 660 }}：该表仅 3 列，
          // 660px 的固定滚动宽度在宽屏下反而限制了表格铺满，且保留了无用的滚动条占位。
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: '暂无修改记录' }}
        />
      </Card>
    </PageContainer>
  );
};

export default Profile;
