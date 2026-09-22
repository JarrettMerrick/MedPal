// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 员工列表页（卡片式），支持工种/科室筛选和关键词搜索。
 * 12 条/页，卡片布局含照片缩略图、基本信息、"查看详情"入口。
 * 
 * 改造说明（v1.1.0）：
 * - [改进] 手写搜索栏 → Input.Search + Button + Select 组件
 * - [改进] 手写卡片 grid → Row/Col + Card 组件
 * - [改进] 手写分页按钮 → Pagination 组件
 * - [改进] 手写 loading/empty → Spin / Empty 组件
 * - [改进] 内联 SVG → @ant-design/icons
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { usePageParams } from '../../hooks/usePageParams';
import { useCompositionInput } from '../../hooks/useCompositionInput';
import { Row, Col, Card, Input, Select, Button, Tag, Typography, Pagination, Spin, Empty, Space, Flex, theme, Segmented, Tooltip } from 'antd';
import { PlusOutlined, SearchOutlined, ClearOutlined, TeamOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import { getStaffList } from '../../api/staff';
import { getDepartmentsByCategory } from '../../api/departments';
import type { Staff } from '../../types/staff';
import { WORK_TYPE_OPTIONS, WORK_TYPE_LABELS, WORK_TYPE_DEPT_CATEGORY, WORK_TYPE_COLOR, WORK_TYPE_HEX } from '../../types/staff';
import { getThumbnailUrl } from '../../utils/imageUtils';
import SafeImage from '../../components/SafeImage';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import { hasPermission, PERM_STAFF_CREATE } from '../../utils/permissions';

const { Text } = Typography;
const { useToken } = theme;

const PAGE_SIZE = 12;

const StaffList: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = useToken();

  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);

  const { params, setParam, setParams } = usePageParams({
    page: '1',
    search: '',
    work_type: '',
    dept: '',
  });

  const page = Number(params.page);
  const search = params.search;
  const workTypeFilter = params.work_type;
  const deptFilter = params.dept;

  // 使用 useCompositionInput 处理 IME 输入
  const {
    value: searchInputValue,
    handleChange: handleSearchChange,
    handleCompositionStart,
    handleCompositionEnd,
  } = useCompositionInput(search, (v) => setParam('search', v));

  const canAddNew = hasPermission(user, PERM_STAFF_CREATE);

  // 工种变化时加载对应科室列表
  useEffect(() => {
    const category = workTypeFilter ? WORK_TYPE_DEPT_CATEGORY[workTypeFilter] || '' : '';
    if (category) {
      getDepartmentsByCategory(category).then(setDepartments);
    } else {
      setDepartments([]);
    }
  }, [workTypeFilter]);

  const loadStaff = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, any> = { page, page_size: PAGE_SIZE, status: 'active' };
      if (search) params.search = search;
      if (workTypeFilter) params.work_type = workTypeFilter;
      if (deptFilter) params.department = deptFilter;
      const data = await getStaffList(params);
      setStaffList(data.items);
      setTotal(data.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [page, search, workTypeFilter, deptFilter]);

  useEffect(() => { loadStaff(); }, [loadStaff]);

  const handleSearch = () => { setParam('page', '1'); };

  const handleWorkTypeChange = (value: string) => {
    setParams({ work_type: value, dept: '', page: '1' });
  };

  const handleClear = () => {
    setParams({ page: '1', search: '', work_type: '', dept: '' });
    setDepartments([]);
  };

  return (
    <PageContainer>
      {/* 头部 */}
      <PageHeader
        title="员工介绍"
        extra={canAddNew ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/staff/new', { state: { returnTo: location.pathname + location.search } })}>
            新增员工
          </Button>
        ) : undefined}
      />

      {/* 搜索 & 筛选 */}
      <Card style={{ marginBottom: token.marginLG }}>
        {/* 搜索行 */}
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="按工号或姓名搜索员工..."
            value={searchInputValue}
            onChange={handleSearchChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            onPressEnter={handleSearch}
            prefix={<SearchOutlined />}
            allowClear
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
          {(search || workTypeFilter || deptFilter) && (
            <Button icon={<ClearOutlined />} onClick={handleClear}>清空</Button>
          )}
        </Space.Compact>

        {/* 筛选项 & 统计 */}
        <Space wrap size={16} align="center" style={{ marginTop: token.marginSM }}>
          {/* 工种 - Segmented 替代 Button 组 */}
          <Space size={8} align="center">
            <Text type="secondary" style={{ fontSize: 12 }}>工种：</Text>
            <Segmented
              size="small"
              value={workTypeFilter || '__all__'}
              onChange={(v) => handleWorkTypeChange(v === '__all__' ? '' : v as string)}
              options={[
                { label: '全部', value: '__all__' },
                ...WORK_TYPE_OPTIONS,
              ]}
            />
          </Space>

          {/* 科室 - 带搜索的 Select */}
          <Space size={8} align="center">
            <Text type="secondary" style={{ fontSize: 12 }}>
              {workTypeFilter === 'nurse' ? '病区' : '科室'}：
            </Text>
            <Select
              value={deptFilter || undefined}
              onChange={(v: string) => { setParams({ dept: v, page: '1' }); }}
              placeholder="全部"
              allowClear
              showSearch
              optionFilterProp="label"
              style={{ minWidth: 160 }}
              options={departments.map((d) => ({ value: d.name, label: d.name }))}
            />
          </Space>

          {/* 统计 */}
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 <Text strong>{total}</Text> 名
            {workTypeFilter && <> · {WORK_TYPE_LABELS[workTypeFilter]}</>}
            {deptFilter && <> · {deptFilter}</>}
          </Text>
        </Space>
      </Card>

      {/* 列表 */}
      {loading ? (
        <Flex justify="center" style={{ padding: token.paddingLG * 3 }}><Spin size="large" /></Flex>
      ) : staffList.length === 0 ? (
        <Empty description="暂无数据" />
      ) : (
        <>
          <Row gutter={[token.marginMD, token.marginMD]}>
            {staffList.map((staff) => {
              const photoUrl = getThumbnailUrl(staff.side_photo) || getThumbnailUrl(staff.front_photo);

              return (
                <Col key={staff.employee_id} xs={24} sm={12} lg={8} xl={6}>
                  <Card
                    hoverable
                    style={{
                      position: 'relative',
                      /* [改造 2026-09-19] 工种色条由「绝对定位的直角矩形」改为卡片左边框。
                         原因：新拟物把卡片圆角提升到 20px，而 4px 宽的直角色条会被卡片
                         裁切成上下断开的细弧，视觉上与卡片脱节。改用 border-left 后，
                         色条会随卡片圆角自然收窄并融入卡片（CSS 边框的固有行为）。
                         工种颜色属业务语义色，保持不变。 */
                      borderLeft: `4px solid ${WORK_TYPE_HEX[staff.work_type] || token.colorBorder}`,
                    }}
                    styles={{ body: { padding: token.paddingMD } }}
                  >
                    <Row gutter={token.marginSM}>
                      {/* 左侧头像 */}
                      <Col span={12} style={{ height: 120 }}>
                        <div style={{ borderRadius: token.borderRadius, overflow: 'hidden', height: 120, backgroundColor: token.colorFill }}>
                          {photoUrl ? (
                            <SafeImage src={staff.side_photo || staff.front_photo} alt={staff.name}
                              style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                          ) : (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: token.colorWhite, fontSize: 28, fontWeight: 'bold' }}>
                              {staff.name.charAt(0)}
                            </div>
                          )}
                        </div>
                      </Col>

                      {/* 右侧信息 */}
                      <Col span={12} style={{ height: 120, display: 'flex', flexDirection: 'column' }}>
                        <Tag color={WORK_TYPE_COLOR[staff.work_type] || 'default'} style={{ marginBottom: token.marginXS, alignSelf: 'flex-start' }}>{WORK_TYPE_LABELS[staff.work_type] || staff.work_type}</Tag>
                        <Text strong ellipsis style={{ display: 'block' }}>{staff.name}</Text>
                        <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{staff.employee_id}</Text>
                        {staff.department && (
                          <Text type="secondary" ellipsis style={{ fontSize: token.fontSizeSM, display: 'block' }}>
                            <TeamOutlined style={{ marginRight: 2 }} />{staff.department}
                          </Text>
                        )}
                        {staff.title && <Text type="secondary" ellipsis style={{ fontSize: token.fontSizeSM, display: 'block' }}>{staff.title}</Text>}
                      </Col>
                    </Row>

                    {/* [新增 2026-09-11] 待审核变更提示（立即生效 + 追认审核）：
                        卡片上显著提示「XX 未审核」，点击进入详情可就地追认/驳回 */}
                    {staff.pending_change && (
                      <Tooltip
                        title={`由 ${staff.pending_change.submitted_by_name || '本人'} 提交：${staff.pending_change.change_summary || ''}`}
                      >
                        <Tag
                          color={staff.pending_change.escalated ? 'red' : 'orange'}
                          style={{ marginTop: token.marginMD, marginInlineEnd: 0 }}
                        >
                          {staff.pending_change.level_label}未审核
                          {staff.pending_change.changed_labels?.length
                            ? ` · ${staff.pending_change.changed_labels.join('、')}`
                            : ''}
                        </Tag>
                      </Tooltip>
                    )}

                    <Button
                      block
                      style={{ marginTop: staff.pending_change ? token.marginXS : token.marginMD }}
                      onClick={() => navigate(`/staff/${staff.employee_id}`, { state: { returnTo: location.pathname + location.search } })}
                    >
                      查看详情
                    </Button>
                  </Card>
                </Col>
              );
            })}
          </Row>

          {/* 分页 */}
          {total > PAGE_SIZE && (
            <Flex justify="center" style={{ marginTop: token.marginLG }}>
              <Pagination
                current={page}
                total={total}
                pageSize={PAGE_SIZE}
                onChange={(p) => setParam('page', String(p))}
                showTotal={(t) => `共 ${t} 条`}
                showSizeChanger={false}
              />
            </Flex>
          )}
        </>
      )}
    </PageContainer>
  );
};

export default StaffList;
