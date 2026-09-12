// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 信息审核页（合并两个审核入口）。
 *
 * [调整 2026-09-11] 原页面只承载「登录页自助注册申请审核」，现按业务口径合并为两个 Tab：
 *
 *   - 账号注册审核（user.approve）：审核登录页自助注册申请，通过后创建可登录账号；
 *   - 信息变更审核（staff.approve）：审核人员信息修改，通过 = 追认，驳回 = 回滚。
 *
 * 两个 Tab 各自独立门禁、独立数据范围：
 *   - 科室管理员：注册申请与人员信息变更均**仅限管辖科室**；
 *   - 超级管理员：全部。
 *
 * 支持站内信「去审核」深链：`/registration-review?tab=change&id=<变更ID>`。
 */
import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { App, Button, Card, Input, Modal, Segmented, Space, Table, Tabs, Tag, Typography, theme } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import {
  approveRegistration,
  listRegistrationRequests,
  rejectRegistration,
  type RegistrationRequestItem,
} from '../../api/registration';
import { getErrorMessage } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
import { hasPermission, PERM_STAFF_APPROVE, PERM_USER_APPROVE } from '../../utils/permissions';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import StaffChangeReview from './StaffChangeReview';

const { Text } = Typography;
const { useToken } = theme;

const PAGE_SIZE = 10;

const WORK_TYPE_LABELS: Record<string, string> = {
  doctor: '医生', nurse: '护士', technician: '技师', admin: '行政',
};
const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'gold', label: '待审核' },
  approved: { color: 'green', label: '已通过' },
  rejected: { color: 'red', label: '已驳回' },
};

const formatTime = (value: string | null): string =>
  value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--';

/** 账号注册审核（原「信息审核」页的表格，逻辑不变） */
const RegistrationTable: React.FC = () => {
  const { message, modal } = App.useApp();
  const { token } = useToken();
  const [status, setStatus] = useState<string>('pending');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<RegistrationRequestItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [rejecting, setRejecting] = useState<RegistrationRequestItem | null>(null);
  const [reason, setReason] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await listRegistrationRequests({ status, page, page_size: PAGE_SIZE });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error('[registration-review] 加载失败:', err);
      message.error(getErrorMessage(err, '加载失败'));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, page]);

  const handleApprove = (record: RegistrationRequestItem) => {
    modal.confirm({
      title: `确认通过 ${record.name}（${record.employee_id}）的注册申请？`,
      content: '通过后将立即创建可登录账号，并同步建立人员档案。',
      okText: '通过',
      onOk: async () => {
        setActing(true);
        try {
          await approveRegistration(record.id);
          message.success('已通过，账号已启用');
          load();
        } catch (err) {
          message.error(getErrorMessage(err, '操作失败'));
        } finally {
          setActing(false);
        }
      },
    });
  };

  const handleReject = async () => {
    if (!rejecting) return;
    if (!reason.trim()) {
      message.error('请填写驳回原因');
      return;
    }
    setActing(true);
    try {
      await rejectRegistration(rejecting.id, reason.trim());
      message.success('已驳回');
      setRejecting(null);
      setReason('');
      load();
    } catch (err) {
      message.error(getErrorMessage(err, '操作失败'));
    } finally {
      setActing(false);
    }
  };

  const columns: ColumnsType<RegistrationRequestItem> = [
    { title: '工号', dataIndex: 'employee_id', key: 'employee_id', width: 110 },
    { title: '姓名', dataIndex: 'name', key: 'name', width: 110 },
    {
      title: '工种', dataIndex: 'work_type', key: 'work_type', width: 90,
      render: (v: string) => WORK_TYPE_LABELS[v] || v,
    },
    { title: '所属科室', dataIndex: 'department', key: 'department', width: 160 },
    {
      title: '提交时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => {
        const meta = STATUS_META[v] || { color: 'default', label: v };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: '审核信息', key: 'review', width: 220,
      render: (_, record) =>
        record.status === 'pending' ? (
          <Text type="secondary">--</Text>
        ) : (
          <div style={{ fontSize: token.fontSizeSM }}>
            <div>
              {record.reviewed_by || '--'} · {formatTime(record.reviewed_at)}
            </div>
            {record.reject_reason && (
              <Text type="danger" style={{ fontSize: token.fontSizeSM }}>
                原因：{record.reject_reason}
              </Text>
            )}
          </div>
        ),
    },
    {
      title: '操作', key: 'action', width: 170, fixed: 'right',
      render: (_, record) =>
        record.status === 'pending' ? (
          <Space>
            <Button
              type="primary"
              size="small"
              icon={<CheckOutlined />}
              loading={acting}
              onClick={() => handleApprove(record)}
            >
              通过
            </Button>
            <Button
              danger
              size="small"
              icon={<CloseOutlined />}
              disabled={acting}
              onClick={() => { setRejecting(record); setReason(''); }}
            >
              驳回
            </Button>
          </Space>
        ) : (
          <Text type="secondary">已处理</Text>
        ),
    },
  ];

  return (
    <Card>
      <div style={{ marginBottom: token.marginMD }}>
        <Segmented
          value={status}
          onChange={(v) => { setStatus(String(v)); setPage(1); }}
          options={[
            { label: '待审核', value: 'pending' },
            { label: '已通过', value: 'approved' },
            { label: '已驳回', value: 'rejected' },
          ]}
        />
        <Text type="secondary" style={{ marginLeft: token.marginSM, fontSize: token.fontSizeSM }}>
          仅显示您管理范围内科室的申请
        </Text>
      </div>

      <Table<RegistrationRequestItem>
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={items}
        loading={loading}
        scroll={{ x: 1080 }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (p) => setPage(p),
        }}
      />

      <Modal
        open={!!rejecting}
        title="驳回注册申请"
        okText="确认驳回"
        okButtonProps={{ danger: true, loading: acting }}
        cancelText="取消"
        onOk={handleReject}
        onCancel={() => { setRejecting(null); setReason(''); }}
      >
        {rejecting && (
          <div style={{ marginBottom: 12 }}>
            <Text>
              申请人：{rejecting.name}（{rejecting.employee_id}） · {rejecting.department}
            </Text>
          </div>
        )}
        <Input.TextArea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="请填写驳回原因（申请人重新提交时会看到该原因）"
          maxLength={200}
          showCount
          rows={3}
        />
      </Modal>
    </Card>
  );
};

const RegistrationReview: React.FC = () => {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const canRegister = hasPermission(user, PERM_USER_APPROVE);
  const canChange = hasPermission(user, PERM_STAFF_APPROVE);
  const focusId = Number(searchParams.get('id')) || undefined;

  const tabFromUrl = searchParams.get('tab') === 'change' ? 'change' : 'register';
  const [tab, setTab] = useState<string>(tabFromUrl);

  // 站内信「去审核」深链：切换 Tab 时同步到 URL，便于分享与刷新保持
  useEffect(() => {
    setTab(tabFromUrl);
  }, [tabFromUrl]);

  // 权限兜底：无注册审核权限时不展示对应 Tab
  useEffect(() => {
    if (tab === 'register' && !canRegister && canChange) setTab('change');
    if (tab === 'change' && !canChange && canRegister) setTab('register');
  }, [tab, canRegister, canChange]);

  const items = [
    canRegister
      ? { key: 'register', label: '账号注册审核', children: <RegistrationTable /> }
      : null,
    canChange
      ? { key: 'change', label: '信息变更审核', children: <StaffChangeReview focusId={focusId} /> }
      : null,
  ].filter(Boolean) as { key: string; label: string; children: React.ReactNode }[];

  return (
    <PageContainer>
      <PageHeader title="信息审核" />

      <Tabs
        activeKey={tab}
        onChange={(k) => {
          setTab(k);
          setSearchParams(k === 'change' ? { tab: 'change' } : {}, { replace: true });
        }}
        items={items}
      />
    </PageContainer>
  );
};

export default RegistrationReview;
