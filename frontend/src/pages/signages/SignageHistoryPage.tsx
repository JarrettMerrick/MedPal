// [修复 2026-09-09] 变更历史独立页：
// ① 状态徽章/卡片头部的 status 此前直接输出英文原值（如 repair_in_progress），改用统一状态映射；
// ② 「字段」列 field_name 与「旧值/新值」列的枚举值（status/validity_type）此前显示 raw 代码，
//    统一接 signageFields 翻译为中文
import React, { useState, useEffect } from 'react';
import { Card, Table, Tag, message } from 'antd';
import { getSignageHistory, getSignage } from '../../api/signage';
import type { SignageHistory as HistoryType, Signage } from '../../api/signage';
import { useParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { SIGNAGE_STATUS_MAP } from '../../constants/signageStatus';
import { signageFieldLabel, formatSignageFieldValue } from '../../constants/signageFields';

const SignageHistoryPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<HistoryType[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [signage, setSignage] = useState<Signage | null>(null);

  useEffect(() => {
    if (!id) return;
    getSignage(Number(id)).then(setSignage).catch(() => {});
    setLoading(true);
    getSignageHistory(Number(id), { page, page_size: 20 }).then((r) => { setHistory(r.items); setTotal(r.total); })
      .catch(() => message.error('获取历史失败')).finally(() => setLoading(false));
  }, [id, page]);

  const columns = [
    // [修复 2026-09-09] 字段名转中文（未知字段回退原值；无字段名为创建标识记录）
    { title: '字段', dataIndex: 'field_name', key: 'field_name', width: 120, render: (v: string) => <Tag>{v ? signageFieldLabel(v) : '创建标识'}</Tag> },
    // [修复 2026-09-09] 枚举值按字段字典转中文（如 status: repair_in_progress → 维修处理中）
    {
      title: '旧值', dataIndex: 'old_value', key: 'old_value', ellipsis: true,
      render: (v: string, r: HistoryType) => formatSignageFieldValue(r.field_name, v) || <span style={{ color: '#ccc' }}>(空)</span>,
    },
    {
      title: '新值', dataIndex: 'new_value', key: 'new_value', ellipsis: true,
      render: (v: string, r: HistoryType) => formatSignageFieldValue(r.field_name, v) || <span style={{ color: '#ccc' }}>(空)</span>,
    },
    { title: 'OA单号', dataIndex: 'oa_number', key: 'oa_number', width: 120 },
    { title: '变更人', dataIndex: 'changed_by', key: 'changed_by', width: 100 },
    { title: '变更时间', dataIndex: 'changed_at', key: 'changed_at', width: 180, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
  ];

  return (
    <div>
      {/* [修复 2026-09-09] 卡片头部状态改用统一映射，显示中文 */}
      {signage && (
        <Card title={`变更历史 - ${signage.code} ${signage.name}`} style={{ marginBottom: 16 }}>
          <p>
            编码: {signage.code} | 分类: {signage.category} | 状态:{' '}
            <Tag color={(SIGNAGE_STATUS_MAP[signage.status] || { color: 'default' }).color}>
              {(SIGNAGE_STATUS_MAP[signage.status] || { label: signage.status }).label}
            </Tag>
          </p>
        </Card>
      )}
      <Card title="变更记录">
        <Table columns={columns} dataSource={history} rowKey="id" loading={loading} pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />
      </Card>
    </div>
  );
};

export default SignageHistoryPage;
