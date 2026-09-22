// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
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
// [统一时间口径] 时间展示一律走 utils/time
import { formatDateTimeStandard } from '../../utils/time';
import { useAuth } from '../../contexts/AuthContext';
import { hasPermission, PERM_STAFF_APPROVE, PERM_USER_APPROVE } from '../../utils/permissions';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
// [新增 2026-09-15] 红底白字待审角标 + 待审数量数据源（与左侧「信息审核」菜单同源）
import ReviewCountBadge from '../../components/ReviewCountBadge';
import { useReviewBadge } from '../../contexts/ReviewBadgeContext';
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

// [统一时间口径] 原 new Date(value).toLocaleString() 会把后端无时区标记的 UTC 串
// 按浏览器本地时区解释（显示比实际少 8 小时），统一改走 utils/time
const formatTime = (value: string | null): string =>
  value ? formatDateTimeStandard(value) : '--';

/** 账号注册审核（原「信息审核」页的表格，逻辑不变） */
const RegistrationTable: React.FC = () => {
  const { message, modal } = App.useApp();
  const { token } = useToken();
  // [新增 2026-09-15] 审核完成后刷新待审角标，使 Tab 与左侧菜单数字立即减少
  const { refresh: refreshBadge } = useReviewBadge();
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
          refreshBadge(); // [新增 2026-09-15] 待审角标即时减一
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
      refreshBadge(); // [新增 2026-09-15] 待审角标即时减一
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
      // [调整 2026-09-19] 去掉固定宽度 220，改为自适应 + 允许换行。
      // 本表原 8 列全部定宽（合计 1130px），无列可伸缩 → 窄屏必然横向滚动。
      // 「审核信息」是全表最长的文本列（审核人 + 时间，可能追加拒绝原因），
      // 交由它吸收剩余空间：宽屏展开、窄屏折行，内容完整可见。
      title: '审核信息', key: 'review',
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 150 } as React.CSSProperties,
      }),
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
        // [调整 2026-09-19] 移除固定 scroll={{ x: 1080 }}（详见 RepairRecords 的说明）
        scroll={{ x: 'max-content' }}
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
  // [新增 2026-09-15] 两个 Tab 各自的待审数量（与左侧「信息审核」菜单同源，红底白字展示）
  const { registerCount, changeCount } = useReviewBadge();
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
      ? {
          key: 'register',
          // [新增 2026-09-15] 与左侧菜单同一原则：Tab 标题右侧显示本类待审条数（红底白字）
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              账号注册审核
              <ReviewCountBadge count={registerCount} />
            </span>
          ),
          children: <RegistrationTable />,
        }
      : null,
    canChange
      ? {
          key: 'change',
          // [新增 2026-09-15] 变更审核同样展示自身的待审条数
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              信息变更审核
              <ReviewCountBadge count={changeCount} />
            </span>
          ),
          children: <StaffChangeReview focusId={focusId} />,
        }
      : null,
  ].filter(Boolean) as { key: string; label: React.ReactNode; children: React.ReactNode }[];

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
