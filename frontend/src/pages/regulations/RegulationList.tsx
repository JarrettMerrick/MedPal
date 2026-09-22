// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 制度列表页，含搜索/筛选/删除确认。
 * [改进] 手写 table → Ant Design Table，手写分页/弹窗 → Pagination / Modal.confirm
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { usePageParams } from '../../hooks/usePageParams';
import { useCompositionInput } from '../../hooks/useCompositionInput';
import { Table, Button, Input, Select, Tag, Typography, Space, Card, Empty, App, Flex, theme } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, LockOutlined } from '@ant-design/icons';
import { getRegulations, getCategories, deleteRegulation } from '../../api/regulations';
import type { Regulation, RegulationCategory } from '../../types/regulation';
import { formatDateTime } from '../../utils/time';
import { useAuth } from '../../contexts/AuthContext';
import { hasPermission, PERM_REGULATION_VIEW, PERM_REGULATION_CREATE, PERM_REGULATION_EDIT, PERM_REGULATION_DELETE } from '../../utils/permissions';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text } = Typography;
const { useToken } = theme;
const PAGE_SIZE = 15;

const RegulationList: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { message, modal } = App.useApp();
  const { token } = useToken();

  const [items, setItems] = useState<Regulation[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<RegulationCategory[]>([]);
  const [loading, setLoading] = useState(false);

  const { params, setParam, setParams } = usePageParams({
    page: '1',
    keyword: '',
    category: '0',
  });

  const page = Number(params.page);
  const keyword = params.keyword;
  const categoryFilter = Number(params.category);

  // 使用 useCompositionInput 处理 IME 输入
  const {
    value: keywordInputValue,
    handleChange: handleKeywordChange,
    handleCompositionStart,
    handleCompositionEnd,
  } = useCompositionInput(keyword, (v) => setParam('keyword', v));

  const canView = hasPermission(user, PERM_REGULATION_VIEW);
  const canCreate = hasPermission(user, PERM_REGULATION_CREATE);
  const canEdit = hasPermission(user, PERM_REGULATION_EDIT);
  const canDelete = hasPermission(user, PERM_REGULATION_DELETE);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await getRegulations({ keyword, category_id: categoryFilter, page, page_size: PAGE_SIZE });
      setItems(res.items);
      setTotal(res.total);
    } finally { setLoading(false); }
  };

  useEffect(() => { getCategories().then(setCategories).catch(() => {}); }, []);
  useEffect(() => { fetchData(); }, [page, categoryFilter, keyword]);

  const handleDelete = (id: number, name: string) => {
    modal.confirm({
      title: '确定要删除该制度吗？',
      content: `「${name}」删除后不可恢复。`,
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try { await deleteRegulation(id); message.success('删除成功'); fetchData(); }
        catch { message.error('删除失败'); }
      },
    });
  };

  if (!canView) {
    return (
      <Flex vertical align="center" justify="center" style={{ padding: token.paddingXL * 2 }}>
        <LockOutlined style={{ fontSize: 48, color: token.colorTextQuaternary, marginBottom: token.marginMD }} />
        <Text type="secondary" style={{ display: 'block', fontSize: token.fontSizeLG }}>无访问权限</Text>
        <Text type="secondary">您没有制度管理模块的访问权限，请联系超级管理员授权。</Text>
      </Flex>
    );
  }

  // [调整 2026-09-19] 列宽按库中**实际数据长度**收敛，消除整表横向滚动：
  //   实测 制度名称 ≤9 字、版本 14 字符、创建人 3 字、类别为短词标签，
  //   据此给各辅助列设置固定宽度，只留「制度名称」不设宽度以吸收剩余空间 ——
  //   这样表格总宽恒等于容器宽度，不会溢出产生横向滚动条。
  //   「制度名称」同时去掉 ellipsis 并允许换行：名称超长时换行展示，
  //   而不是被截成省略号导致信息不可读（这是原实现的主要问题）。
  const columns = [
    { title: '序号', width: 72, render: (_: any, __: any, idx: number) => (page - 1) * PAGE_SIZE + idx + 1 },
    {
      title: '制度名称',
      dataIndex: 'name',
      key: 'name',
      // 不设 width：作为主内容列吸收剩余空间；允许换行 + 兜底最小宽度
      // （style 需断言为 CSSProperties，否则 'break-word' 会被推断为 string，
      //   与 CSS 字面量类型不兼容 —— TS2322）
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 200 } as React.CSSProperties,
      }),
    },
    { title: '所属类别', dataIndex: 'category_name', key: 'category_name', width: 140, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    { title: '版本', dataIndex: 'version', key: 'version', width: 150, render: (v: string) => v || '-' },
    { title: '创建人', dataIndex: 'created_by', key: 'created_by', width: 100, render: (v: string) => v || '-' },
    { title: '最后修改', dataIndex: 'updated_at', key: 'updated_at', width: 170, render: (v: string) => v ? formatDateTime(v) : '-' },
    {
      title: '操作', key: 'actions', width: 180,
      render: (_: any, record: Regulation) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/regulations/view/${record.id}`, { state: { returnTo: location.pathname + location.search } })}>查看</Button>
          {canEdit && <Button type="link" size="small" icon={<EditOutlined />} onClick={() => navigate(`/regulations/edit/${record.id}`, { state: { returnTo: location.pathname + location.search } })}>编辑</Button>}
          {canDelete && <Button type="link" danger size="small" icon={<DeleteOutlined />} onClick={() => handleDelete(record.id, record.name)}>删除</Button>}
        </Space>
      ),
    },
  ];

  return (
    <PageContainer>
      <PageHeader
        title="制度管理"
        extra={canCreate ? <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/regulations/new', { state: { returnTo: location.pathname + location.search } })}>新增制度</Button> : undefined}
      />

      <Card style={{ marginBottom: token.marginLG }}>
        <Space wrap>
          <Input.Search
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="regulation-search"
            placeholder="搜索制度名称..."
            value={keywordInputValue} 
            onChange={handleKeywordChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            onSearch={() => setParam('page', '1')} 
            style={{ width: 260 }} 
          />
          <Select
            value={categoryFilter}
            onChange={(v) => setParams({ category: String(v), page: '1' })}
            placeholder="全部类别"
            style={{ minWidth: 160 }}
            options={[{ value: 0, label: '全部类别' }, ...categories.map((c) => ({ value: c.id, label: c.name }))]}
          />
        </Space>
      </Card>

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        locale={{ emptyText: <Empty description="暂无制度数据" /> }}
        pagination={{
          current: page,
          total,
          pageSize: PAGE_SIZE,
          onChange: (p) => setParam('page', String(p)),
          showTotal: (t) => `共 ${t} 条`,
          showSizeChanger: false,
        }}
      />
    </PageContainer>
  );
};

export default RegulationList;
