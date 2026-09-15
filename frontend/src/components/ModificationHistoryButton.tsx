// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 修改历史查询按钮 + 弹窗。
 *
 * [新增 2026-09-15] 需求：人员详情页、科室详情页在「编辑」按钮左侧提供修改历史查询，
 * 可查看所修改的字段及修改前 / 修改后的对比，只保留最近三次修改。
 *
 * 设计要点：
 * - **即开即查**：每次打开弹窗都重新拉取，保证刚编辑完再点开就能看到最新一条；
 * - **只用最近三次**：请求条数固定为 MODIFICATION_HISTORY_LIMIT(3)，
 *   同时在弹窗顶部说明「共 N 次、仅显示最近 3 次」，避免使用者误以为只有三次修改；
 * - **只读**：不提供任何回滚 / 确认动作，与原已下线「信息修改」流程无关；
 * - **字段级对比**：后端把变更摘要解析成「字段 / 修改前 / 修改后」三列；
 *   解析不出来的整句（如「新增人员: ...」）原样作为说明展示，不丢信息。
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  App, Alert, Button, Empty, Modal, Skeleton, Space, Table, Tag, Typography, theme,
} from 'antd';
import { HistoryOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getModificationHistory,
  MODIFICATION_HISTORY_LIMIT,
  type ModificationFieldDiff,
  type ModificationHistoryItem,
} from '../api/modificationHistory';
import { formatDateTimeStandard } from '../utils/time';
import { getErrorMessage } from '../utils/format';

const { Text } = Typography;
const { useToken } = theme;

/** 前后值单元格：允许长文本（如科室介绍）换行，避免撑破表格 */
const VALUE_CELL_STYLE: React.CSSProperties = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
};

interface ModificationHistoryButtonProps {
  /** 实体类型：staff=人员详情页，department=科室详情页 */
  entityType: 'staff' | 'department';
  /** 人员为工号，科室为科室 ID */
  entityId: string | number;
  /** 查询对象名称，仅用于弹窗标题（如人员姓名 / 科室名称） */
  entityName?: string;
  /** 按钮尺寸，跟随所在页面工具栏 */
  size?: 'small' | 'middle' | 'large';
}

const ModificationHistoryButton: React.FC<ModificationHistoryButtonProps> = ({
  entityType, entityId, entityName, size,
}) => {
  const { message } = App.useApp();
  const { token } = useToken();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ModificationHistoryItem[]>([]);
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getModificationHistory(entityType, entityId, MODIFICATION_HISTORY_LIMIT);
      setItems(res.items || []);
      setTotal(res.total ?? (res.items?.length || 0));
    } catch (err) {
      // 失败时清空列表并给出明确错误，避免残留上一次的旧数据造成误读
      setItems([]);
      setTotal(0);
      setError(getErrorMessage(err));
      message.error(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId, message]);

  // 每次打开都重新查询：编辑保存后再次点开即可看到最新记录
  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const columns: ColumnsType<ModificationFieldDiff> = [
    {
      title: '修改字段',
      dataIndex: 'label',
      width: 120,
      render: (label: string) => <Text strong>{label}</Text>,
    },
    {
      title: '修改前',
      dataIndex: 'before',
      render: (value: string) => (
        <Text type="secondary" style={VALUE_CELL_STYLE}>{value || '（空）'}</Text>
      ),
    },
    {
      title: '修改后',
      dataIndex: 'after',
      render: (value: string) => (
        <Text strong style={{ ...VALUE_CELL_STYLE, color: token.colorSuccess }}>
          {value || '（空）'}
        </Text>
      ),
    },
  ];

  return (
    <>
      <Button icon={<HistoryOutlined />} size={size} onClick={() => setOpen(true)}>
        修改历史
      </Button>

      <Modal
        open={open}
        title={entityName ? `修改历史：${entityName}` : '修改历史'}
        onCancel={() => setOpen(false)}
        width={720}
        footer={[
          <Button key="refresh" icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>,
          <Button key="close" type="primary" onClick={() => setOpen(false)}>关闭</Button>,
        ]}
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : error ? (
          <Alert type="error" showIcon message="修改历史加载失败" description={error} />
        ) : items.length === 0 ? (
          <Empty description="暂无修改记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {total > items.length
                ? `该对象累计被修改 ${total} 次，为便于查看仅显示最近 ${items.length} 次`
                : `共 ${items.length} 次修改记录`}
            </Text>

            {items.map((item, index) => (
              <div
                key={item.id}
                style={{
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: token.borderRadiusLG,
                  padding: 12,
                  background: token.colorFillQuaternary,
                }}
              >
                {/* 记录头：第几次（最近标记）+ 时间 + 操作人 */}
                <Space size={8} wrap style={{ marginBottom: item.fields.length ? 8 : 0 }}>
                  {index === 0 && <Tag color="blue" style={{ marginInlineEnd: 0 }}>最近一次</Tag>}
                  <Text strong>{formatDateTimeStandard(item.modified_at)}</Text>
                  <Text type="secondary">
                    操作人：{item.modified_by_name || item.modified_by || '系统'}
                    {/* 姓名解析失败时后端会回落为工号，此时不再重复追加括号工号 */}
                    {item.modified_by_name && item.modified_by && item.modified_by_name !== item.modified_by
                      ? `（${item.modified_by}）`
                      : ''}
                  </Text>
                </Space>

                {/* 字段级前后对比 */}
                {item.fields.length > 0 && (
                  <Table<ModificationFieldDiff>
                    columns={columns}
                    dataSource={item.fields}
                    rowKey={(_, rowIndex) => `${item.id}-${rowIndex}`}
                    size="small"
                    pagination={false}
                    bordered={false}
                  />
                )}

                {/* 说明性文字（新增人员 / 删除人员 / 特色技术统计等无法拆成前后值的描述） */}
                {item.notes.length > 0 && (
                  <div style={{ marginTop: item.fields.length ? 8 : 0 }}>
                    {item.notes.map((note, noteIndex) => (
                      <Text
                        key={noteIndex}
                        type="secondary"
                        style={{ ...VALUE_CELL_STYLE, display: 'block', fontSize: 12 }}
                      >
                        {note}
                      </Text>
                    ))}
                  </div>
                )}

                {/* 兜底：摘要既无字段对比也无说明时，直接展示原始文本 */}
                {item.fields.length === 0 && item.notes.length === 0 && (
                  <Text type="secondary" style={VALUE_CELL_STYLE}>
                    {item.summary || '无字段变化'}
                  </Text>
                )}
              </div>
            ))}
          </Space>
        )}
      </Modal>
    </>
  );
};

export default ModificationHistoryButton;
