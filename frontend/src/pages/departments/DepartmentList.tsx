// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 科室列表页（卡片式），支持搜索和分类展示。
 * 卡片包含科室名称、介绍、特色技术/设备统计、查看详情 + 删除操作。
 * 
 * 改造说明（v1.1.0）：
 * - [改进] 手写搜索 → Input.Search + Button
 * - [改进] 手写卡片 grid → Row/Col + Card
 * - [改进] 手写分页 → Pagination
 * - [改进] confirm/alert → Modal.confirm / message
 * - [改进] 内联 SVG → @ant-design/icons
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { usePageParams } from '../../hooks/usePageParams';
import { useCompositionInput } from '../../hooks/useCompositionInput';
import { Row, Col, Card, Input, Button, Tag, Typography, Pagination, Spin, Empty, Space, App, Flex, theme } from 'antd';
import { PlusOutlined, SearchOutlined, DeleteOutlined } from '@ant-design/icons';
import { getDepartments, deleteDepartment } from '../../api/departments';
import { useAuth } from '../../contexts/AuthContext';
import { useLayout } from '../../contexts/LayoutContext';
import type { Department } from '../../types/department';
import { DEPT_CATEGORY_HEX } from '../../types/staff';
import { hasPermission, PERM_DEPT_CREATE, PERM_DEPT_DELETE } from '../../utils/permissions';
import PageContainer from '../../components/PageContainer';
// [修复 2026-09-02] P4: 导入统一错误处理函数
import { getErrorMessage } from '../../utils/format';
import PageHeader from '../../components/PageHeader';

const { Text, Paragraph } = Typography;
const { useToken } = theme;
const PAGE_SIZE = 20;

const DepartmentList: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const { sidebarCollapsed } = useLayout();
  const { message, modal } = App.useApp();
  const { token } = useToken();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const { params, setParam, setParams } = usePageParams({
    page: '1',
    search: '',
  });

  const page = Number(params.page);
  const search = params.search;

  // 使用 useCompositionInput 处理 IME 输入
  const {
    value: searchInputValue,
    handleChange: handleSearchChange,
    handleCompositionStart,
    handleCompositionEnd,
  } = useCompositionInput(search, (v) => setParam('search', v));

  const canCreate = hasPermission(user, PERM_DEPT_CREATE);
  const canDelete = hasPermission(user, PERM_DEPT_DELETE);

  const fetchData = async (p = page, s = search) => {
    setLoading(true);
    try {
      const res = await getDepartments({ page: p, page_size: PAGE_SIZE, search: s || undefined });
      setDepartments(res.items);
      setTotal(res.total);
    } finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, [page, search]);

  const handleSearch = () => { setParam('page', '1'); };

  const handleDelete = (id: number, name: string) => {
    modal.confirm({
      title: `确定要删除科室「${name}」吗？`,
      content: '此操作不可撤销！删除后数据无法恢复。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteDepartment(id);
          message.success('删除成功');
          fetchData();
        } catch (err) {
          message.error(getErrorMessage(err, '删除失败'));
        }
      },
    });
  };

  // 响应式列数（与侧边栏状态联动）
  const getColSpan = () => {
    if (sidebarCollapsed) return { xs: 24, sm: 12, lg: 8, xl: 6 };
    return { xs: 24, sm: 12, lg: 8, xl: 6, xxl: 6 };
  };

  return (
    <PageContainer>
      {/* 头部 */}
      <PageHeader
        title="科室管理"
        extra={canCreate ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/departments/new', { state: { returnTo: location.pathname + location.search } })}>
            新增科室
          </Button>
        ) : undefined}
      />

      {/* 搜索 */}
      <Card style={{ marginBottom: token.marginLG }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="department-search"
            placeholder="搜索科室名称..."
            value={searchInputValue}
            onChange={handleSearchChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            onPressEnter={handleSearch}
            prefix={<SearchOutlined />}
            allowClear
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </Space.Compact>
      </Card>

      {/* 列表 */}
      {loading ? (
        <Flex justify="center" style={{ padding: token.paddingLG * 3 }}><Spin size="large" /></Flex>
      ) : departments.length === 0 ? (
        <Empty description="暂无数据" />
      ) : (
        <>
          <Row gutter={[token.marginMD, token.marginMD]}>
            {departments.map((d) => (
              <Col key={d.id} {...getColSpan()}>
                <Card
                  hoverable
                  style={{ background: token.colorBgContainer, position: 'relative' }}
                  styles={{ body: { padding: token.paddingMD } }}
                >
                  {/* 左侧科室类别色条 */}
                  <div style={{
                    position: 'absolute', left: 0, top: 0, bottom: 0, width: 4,
                    background: DEPT_CATEGORY_HEX[d.category] || token.colorBorder,
                  }} />
                  <Tag color={DEPT_CATEGORY_HEX[d.category] || 'blue'} style={{ marginBottom: token.marginXS }}>{d.category}</Tag>
                  <Text strong style={{ display: 'block', marginBottom: token.marginXS, fontSize: token.fontSizeLG }}>{d.name}</Text>
                  <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ fontSize: token.fontSizeSM }}>
                    {d.description || '暂无介绍'}
                  </Paragraph>
                  <Space size={token.marginLG} style={{ marginBottom: token.marginSM }}>
                    {d.specialties?.length > 0 && <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{d.specialties.length} 项特色技术</Text>}
                    {d.equipments?.length > 0 && <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{d.equipments.length} 台特色设备</Text>}
                  </Space>
                  <Button block onClick={() => navigate(`/departments/view/${d.id}`, { state: { returnTo: location.pathname + location.search } })}>查看详情</Button>
                  {canDelete && (
                    <Button
                      block
                      danger
                      icon={<DeleteOutlined />}
                      style={{ marginTop: token.marginXS }}
                      onClick={() => handleDelete(d.id, d.name)}
                    >
                      删除
                    </Button>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          {total > PAGE_SIZE && (
            <Flex justify="center" style={{ marginTop: token.marginLG }}>
              <Pagination current={page} total={total} pageSize={PAGE_SIZE} onChange={(p) => setParam('page', String(p))} showTotal={(t) => `共 ${t} 条`} showSizeChanger={false} />
            </Flex>
          )}
        </>
      )}
    </PageContainer>
  );
};

export default DepartmentList;
