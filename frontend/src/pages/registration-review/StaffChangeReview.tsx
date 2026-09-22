// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 信息变更审核（信息审核 → 信息变更审核 Tab）。
 *
 * [新增 2026-09-11] 人员信息「立即生效 + 追认审核」的审核侧：
 * - 提交即生效（页面立刻显示最新值），此处审核 = 追认或回滚；
 * - 通过 = 追认（延迟生效字段如科室/工种此刻落库）；驳回 = 回滚到提交前旧值；
 * - 冲突提示：若该字段在提交后又被他人改动，系统**不会**自动回滚，
 *   仅提示人工核对，避免覆盖他人的合法修改；
 * - 范围：超级管理员可审全部（含超时升级件）；科室管理员仅审管辖科室的科室级变更，
 *   且任何人都不能审核自己提交的变更（禁止自审）。
 */
import React, { useEffect, useState } from 'react';
import { App, Alert, Button, Card, Input, Modal, Segmented, Space, Table, Tag, Tooltip, Typography, theme } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CheckOutlined, CloseOutlined, WarningOutlined } from '@ant-design/icons';
import {
  approveStaffChange,
  listStaffChanges,
  rejectStaffChange,
  type StaffChangeItem,
} from '../../api/staffChanges';
import { getErrorMessage } from '../../utils/format';
// [统一时间口径] 时间展示一律走 utils/time
import { formatDateTimeStandard } from '../../utils/time';
// [新增 2026-09-15] 审核完成后刷新待审角标（Tab 与左侧「信息审核」菜单同源）
import { useReviewBadge } from '../../contexts/ReviewBadgeContext';

const { Text } = Typography;
const { useToken } = theme;

const PAGE_SIZE = 10;

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'gold', label: '待审核' },
  approved: { color: 'green', label: '已追认' },
  rejected: { color: 'red', label: '已驳回' },
  cancelled: { color: 'gray', label: '已撤回' },
};

const SOURCE_LABELS: Record<string, string> = {
  self: '个人中心',
  admin: '人员编辑',
  photo: '照片上传',
};

// [统一时间口径] 原 new Date(value).toLocaleString() 会把后端无时区标记的 UTC 串
// 按浏览器本地时区解释（显示比实际少 8 小时），统一改走 utils/time
const formatTime = (value: string | null): string =>
  value ? formatDateTimeStandard(value) : '--';

const StaffChangeReview: React.FC<{ focusId?: number }> = ({ focusId }) => {
  const { message, modal } = App.useApp();
  const { token } = useToken();
  // [新增 2026-09-15] 审核完成后刷新待审角标，使 Tab 与左侧菜单数字立即减少
  const { refresh: refreshBadge } = useReviewBadge();
  const [status, setStatus] = useState<string>('pending');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<StaffChangeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [rejecting, setRejecting] = useState<StaffChangeItem | null>(null);
  const [reason, setReason] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await listStaffChanges({ status, page, page_size: PAGE_SIZE });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error('[staff-change-review] 加载失败:', err);
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

  // 站内信「去审核」跳转过来时，确保停留在待审核页签
  useEffect(() => {
    if (focusId) {
      setStatus('pending');
      setPage(1);
    }
  }, [focusId]);

  const handleApprove = (record: StaffChangeItem) => {
    modal.confirm({
      title: `确认通过 ${record.staff_name}（${record.employee_id}）的信息变更？`,
      content: (
        <div>
          <div style={{ marginBottom: 8 }}>{record.change_summary}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            通过即为「追认」：该变更已生效，科室/工种等延迟生效字段将在通过后写入。
          </Text>
        </div>
      ),
      okText: '通过',
      onOk: async () => {
        setActing(true);
        try {
          const res = await approveStaffChange(record.id);
          if (res.conflict_fields?.length) {
            message.warning('已通过。注意：部分字段在提交后又被修改，请核对最新值');
          } else {
            message.success('已通过');
          }
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
      const res = await rejectStaffChange(rejecting.id, reason.trim());
      if (res.conflict_fields?.length) {
        message.warning('已驳回。部分字段在提交后又被修改，未自动回滚，请人工核对');
      } else {
        message.success('已驳回，相关信息已回滚');
      }
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

  const columns: ColumnsType<StaffChangeItem> = [
    {
      title: '人员', key: 'staff', width: 190,
      render: (_, r) => (
        <div>
          <div>{r.staff_name}（{r.employee_id}）</div>
          <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{r.department || '--'}</Text>
        </div>
      ),
    },
    {
      title: '变更内容', key: 'summary',
      render: (_, r) => (
        <div style={{ fontSize: token.fontSizeSM }}>
          <div>{r.change_summary || '--'}</div>
          <Space size={4} wrap style={{ marginTop: 4 }}>
            {r.changed_labels.map((l) => <Tag key={l}>{l}</Tag>)}
            {r.conflict_fields.length > 0 && (
              <Tooltip title="该字段在提交后又被他人修改，驳回时不会自动回滚，请人工核对">
                <Tag icon={<WarningOutlined />} color="orange">存在并发修改</Tag>
              </Tooltip>
            )}
          </Space>
        </div>
      ),
    },
    {
      title: '提交人 / 来源', key: 'submitter', width: 170,
      render: (_, r) => (
        <div style={{ fontSize: token.fontSizeSM }}>
          <div>{r.submitted_by_name || r.submitted_by}</div>
          <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            {SOURCE_LABELS[r.source] || r.source} · {formatTime(r.submitted_at)}
          </Text>
        </div>
      ),
    },
    {
      title: '审核人范围', key: 'level', width: 120,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Tag color={r.review_level === 'admin' ? 'purple' : 'blue'}>{r.level_label}审核</Tag>
          {r.escalated_at && <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>已超时升级</Text>}
        </Space>
      ),
    },
    {
      title: '状态', key: 'status', width: 90,
      render: (_, r) => {
        const meta = STATUS_META[r.status] || { color: 'default', label: r.status };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: '审核信息', key: 'review', width: 210,
      render: (_, r) =>
        r.status === 'pending' ? (
          <Text type="secondary">--</Text>
        ) : (
          <div style={{ fontSize: token.fontSizeSM }}>
            <div>{r.reviewed_by_name || r.reviewed_by || r.review_note || '--'} · {formatTime(r.reviewed_at)}</div>
            {r.reject_reason && (
              <Text type="danger" style={{ fontSize: token.fontSizeSM }}>原因：{r.reject_reason}</Text>
            )}
            {r.rollback_note && (
              <Text type="warning" style={{ fontSize: token.fontSizeSM }}>{r.rollback_note}</Text>
            )}
          </div>
        ),
    },
    {
      title: '操作', key: 'action', width: 170, fixed: 'right',
      render: (_, r) =>
        r.status === 'pending' && r.can_review ? (
          <Space>
            <Button
              type="primary" size="small" icon={<CheckOutlined />} loading={acting}
              onClick={() => handleApprove(r)}
            >
              追认
            </Button>
            <Button
              danger size="small" icon={<CloseOutlined />} disabled={acting}
              onClick={() => { setRejecting(r); setReason(''); }}
            >
              驳回
            </Button>
          </Space>
        ) : r.status === 'pending' ? (
          <Tooltip title="不能审核自己提交的变更，或该变更不在您的审核范围内">
            <Text type="secondary">待他人审核</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">已处理</Text>
        ),
    },
  ];

  return (
    <Card>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: token.marginMD }}
        message="人员信息提交后已立即生效，此处审核为「追认」：通过 = 确认生效；驳回 = 回滚为修改前的值。"
      />
      <div style={{ marginBottom: token.marginMD }}>
        <Segmented
          value={status}
          onChange={(v) => { setStatus(String(v)); setPage(1); }}
          options={[
            { label: '待审核', value: 'pending' },
            { label: '已追认', value: 'approved' },
            { label: '已驳回', value: 'rejected' },
            { label: '已撤回', value: 'cancelled' },
          ]}
        />
        <Text type="secondary" style={{ marginLeft: token.marginSM, fontSize: token.fontSizeSM }}>
          仅显示您审核范围内的变更（科室管理员仅本科室，且不能审核自己提交的）
        </Text>
      </div>

      <Table<StaffChangeItem>
        rowKey="id"
        size="middle"
        columns={columns}
        dataSource={items}
        loading={loading}
        // [调整 2026-09-19] 移除固定 scroll={{ x: 1180 }}（详见 RepairRecords 的说明）：
        // 固定像素值会强制保留横向滚动条。改用 'max-content' 让宽度由内容决定 ——
        // 内容未超容器时**不出现**滚动条，真的超长时（如超长变更摘要）才允许内部滚动，
        // 既满足"不出现横向滚动"，又不会把内容硬压成不可读。
        scroll={{ x: 'max-content' }}
        rowClassName={(r) => (focusId && r.id === focusId ? 'ant-table-row-selected' : '')}
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
        title="驳回信息变更"
        okText="确认驳回"
        okButtonProps={{ danger: true, loading: acting }}
        cancelText="取消"
        onOk={handleReject}
        onCancel={() => { setRejecting(null); setReason(''); }}
      >
        {rejecting && (
          <div style={{ marginBottom: 12 }}>
            <Text>
              {rejecting.staff_name}（{rejecting.employee_id}） · {rejecting.department}
            </Text>
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{rejecting.change_summary}</Text>
            </div>
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 10 }}
              message="驳回后，本次修改将回滚为修改前的值（若该字段期间又被他人修改，则只提示、不覆盖）。"
            />
          </div>
        )}
        <Input.TextArea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="请填写驳回原因（提交人会收到站内信）"
          maxLength={200}
          showCount
          rows={3}
        />
      </Modal>
    </Card>
  );
};

export default StaffChangeReview;
