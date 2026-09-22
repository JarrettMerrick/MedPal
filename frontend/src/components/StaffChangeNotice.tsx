// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 人员信息「待审核」提示条 + 审核操作（可复用）。
 *
 * [新增 2026-09-11] 人员信息采用「立即生效 + 追认审核」：
 * 提交后页面立刻显示最新值，此处负责在**显著位置**提示「XX 未审核」；
 * 若当前登录人恰为该变更的审核人（科室负责人/超管），同时给出「追认 / 驳回」入口，
 * 使审核既能在「信息审核」菜单集中处理，也能在人员介绍页面就地确认。
 */
import React, { useState } from 'react';
import { Alert, App, Button, Input, Space, Tag, Typography, theme } from 'antd';
import { CheckOutlined, CloseOutlined, WarningOutlined } from '@ant-design/icons';
import {
  approveStaffChange,
  rejectStaffChange,
  type StaffChangeItem,
} from '../api/staffChanges';
import { getErrorMessage } from '../utils/format';
// [统一时间口径] 时间展示一律走 utils/time
import { formatDateTimeStandard } from '../utils/time';

const { Text } = Typography;
const { useToken } = theme;

// [统一时间口径] 原 new Date(value).toLocaleString() 会把后端无时区标记的 UTC 串
// 按浏览器本地时区解释（显示比实际少 8 小时），统一改走 utils/time
const formatTime = (value: string | null): string =>
  value ? formatDateTimeStandard(value) : '--';

export interface StaffChangeNoticeProps {
  /** 该人员的待审变更列表（为空则不渲染任何内容） */
  changes: StaffChangeItem[];
  /** 审核完成后的刷新回调 */
  onReviewed?: () => void;
  /** 是否展示「追认/驳回」按钮（默认展示，且仅对 can_review 的条目生效） */
  showActions?: boolean;
  /** 自定义标题前缀，如「我的信息」 */
  titlePrefix?: string;
}

const StaffChangeNotice: React.FC<StaffChangeNoticeProps> = ({
  changes, onReviewed, showActions = true, titlePrefix,
}) => {
  const { message, modal } = App.useApp();
  const { token } = useToken();
  const [acting, setActing] = useState(false);

  if (!changes || changes.length === 0) return null;

  const handleApprove = async (item: StaffChangeItem) => {
    setActing(true);
    try {
      const res = await approveStaffChange(item.id);
      if (res.conflict_fields?.length) {
        message.warning('已追认。注意：部分字段在提交后又被修改，请核对最新值');
      } else {
        message.success('已通过（追认）');
      }
      onReviewed?.();
    } catch (err) {
      message.error(getErrorMessage(err, '操作失败'));
    } finally {
      setActing(false);
    }
  };

  const handleReject = (item: StaffChangeItem) => {
    let reason = '';
    modal.confirm({
      title: `驳回 ${item.staff_name}（${item.employee_id}）的信息变更？`,
      okText: '确认驳回',
      okType: 'danger',
      cancelText: '取消',
      content: (
        <div>
          <div style={{ marginBottom: 8 }}>
            <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{item.change_summary}</Text>
          </div>
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 10 }}
            message="驳回后本次修改将回滚为修改前的值（若期间又被他人修改，则只提示、不覆盖）。"
          />
          <Input.TextArea
            placeholder="请填写驳回原因（提交人会收到站内信）"
            maxLength={200}
            showCount
            rows={3}
            onChange={(e) => { reason = e.target.value; }}
          />
        </div>
      ),
      onOk: async () => {
        if (!reason.trim()) {
          message.error('请填写驳回原因');
          throw new Error('reason required');
        }
        try {
          const res = await rejectStaffChange(item.id, reason.trim());
          if (res.conflict_fields?.length) {
            message.warning('已驳回。部分字段在提交后又被修改，未自动回滚，请人工核对');
          } else {
            message.success('已驳回，相关信息已回滚');
          }
          onReviewed?.();
        } catch (err) {
          message.error(getErrorMessage(err, '操作失败'));
          throw err;
        }
      },
    });
  };

  return (
    <Space direction="vertical" style={{ width: '100%', marginBottom: token.marginMD }} size={token.marginSM}>
      {changes.map((item) => (
        <Alert
          key={item.id}
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message={
            <Space wrap size={token.marginXS}>
              <Text strong>
                {titlePrefix ? `${titlePrefix}` : ''}
                {(item.level_label || '负责人')}未审核
              </Text>
              {item.changed_labels.map((l) => <Tag key={l} color="orange">{l}</Tag>)}
              {item.escalated_at && <Tag color="red">已超时升级超管</Tag>}
            </Space>
          }
          description={
            <div>
              <div style={{ fontSize: token.fontSizeSM }}>
                由 {item.submitted_by_name || item.submitted_by} 于 {formatTime(item.submitted_at)} 提交：
                {' '}{item.change_summary}
              </div>
              <div style={{ fontSize: token.fontSizeSM, color: token.colorTextTertiary, marginTop: 2 }}>
                该修改已立即生效，未审核通过前如被驳回将自动回滚。
              </div>
              {showActions && item.can_review && (
                <Space style={{ marginTop: token.marginXS }}>
                  <Button
                    type="primary" size="small" icon={<CheckOutlined />} loading={acting}
                    onClick={() => handleApprove(item)}
                  >
                    通过（追认）
                  </Button>
                  <Button
                    danger size="small" icon={<CloseOutlined />} disabled={acting}
                    onClick={() => handleReject(item)}
                  >
                    驳回
                  </Button>
                </Space>
              )}
            </div>
          }
        />
      ))}
    </Space>
  );
};

export default StaffChangeNotice;
