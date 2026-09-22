// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 离职人员（原「员工休息区」）
 *
 * [调整 2026-09-11]
 * - 更名「员工休息区」→「离职人员」，语义更直白；
 * - 显示离职时间与离职原因（新增字段）；
 * - 工种筛选补齐 技师 / 行政（原先只有 医生 / 护士）；
 * - 引入**离职保留期策略**（默认 180 天 ≈ 6 个月）：
 *     · 在档：离职未满保留期 → 逐条展示，可查看详情、恢复在职；
 *     · 待清理：离职已满保留期 → 档案仅保留统计，系统已私信超管提醒手动删除登录账号，
 *       此处只读展示，方便管理员对照处理。
 */

import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { usePageParams } from '../../hooks/usePageParams';
import { useCompositionInput } from '../../hooks/useCompositionInput';
import {
  Row, Col, Card, Input, Button, Tag, Typography, Pagination, Spin, Space, App, Flex,
  Statistic, Alert, Tooltip, theme,
} from 'antd';
import { TeamOutlined, DeleteOutlined } from '@ant-design/icons';
import { getResignedStaff, updateStaffStatus } from '../../api/staff';
import { useAuth } from '../../contexts/AuthContext';
import { useLayout } from '../../contexts/LayoutContext';
import SafeImage from '../../components/SafeImage';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import type { Staff, StaffListResponse } from '../../types/staff';
import { WORK_TYPE_LABELS, WORK_TYPE_COLOR, WORK_TYPE_OPTIONS } from '../../types/staff';
import { hasPermission, PERM_STAFF_STATUS } from '../../utils/permissions';
import { formatDateTime } from '../../utils/time';

const { Text } = Typography;
const { useToken } = theme;
const PAGE_SIZE = 20;

type Scope = 'active' | 'archived';

const StaffRestArea: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const { sidebarCollapsed } = useLayout();
  const { message, modal } = App.useApp();
  const { token } = useToken();
  const [staffList, setStaffList] = useState<Staff[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<StaffListResponse['stats']>(null);
  const [loading, setLoading] = useState(false);
  const canRestore = hasPermission(user, PERM_STAFF_STATUS);

  const { params, setParam, setParams } = usePageParams({
    page: '1',
    search: '',
    tab: 'all',
    scope: 'active',
  });

  const page = Number(params.page);
  const search = params.search;
  const activeTab = params.tab || 'all';
  const scope = (params.scope || 'active') as Scope;

  // 使用 useCompositionInput 处理 IME 输入
  const {
    value: searchInputValue,
    handleChange: handleSearchChange,
    handleCompositionStart,
    handleCompositionEnd,
  } = useCompositionInput(search, (v) => setParam('search', v));

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const queryParams: Record<string, unknown> = { page, page_size: PAGE_SIZE, scope };
      if (search) queryParams.search = search;
      if (activeTab !== 'all') queryParams.work_type = activeTab;
      const res = await getResignedStaff(queryParams);
      setStaffList(res.items);
      setTotal(res.total);
      setStats(res.stats ?? null);
    } finally { setLoading(false); }
  }, [page, search, activeTab, scope]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSearch = () => { setParam('page', '1'); };

  const handleRestore = (item: Staff) => {
    modal.confirm({
      title: `确定要将 ${item.name} 恢复为在职状态吗？`,
      content: '恢复后将清空其离职记录（离职时间/原因），登录账号同步恢复启用。',
      okText: '确认恢复',
      cancelText: '取消',
      onOk: async () => {
        try {
          await updateStaffStatus(item.employee_id, 'active');
          message.success(`已恢复 ${item.name} 在职状态`);
          fetchData();
        } catch (err: unknown) {
          const axiosErr = err as { response?: { data?: { detail?: string } } };
          message.error(axiosErr.response?.data?.detail || '操作失败');
        }
      },
    });
  };

  const tabOptions = [
    { key: 'all', label: '全部' },
    ...WORK_TYPE_OPTIONS.map((o) => ({ key: o.value as string, label: o.label })),
  ];

  // 响应式列数
  const colSpan = sidebarCollapsed
    ? { xs: 24, sm: 12, lg: 8, xl: 6 }
    : { xs: 24, sm: 12, lg: 8, xl: 8, xxl: 6 };

  const retentionMonths = stats ? Math.round(stats.retention_days / 30) : 6;

  return (
    <PageContainer>
      <PageHeader
        title="离职人员"
        description={`已离职人员档案；离职满 ${retentionMonths} 个月后仅保留统计，并提醒管理员删除登录账号`}
      />

      {/* 保留期统计 */}
      <Row gutter={[token.marginMD, token.marginMD]} style={{ marginBottom: token.marginMD }}>
        <Col xs={24} sm={8}>
          <Card size="small"><Statistic title="离职总人数" value={stats?.total ?? total} /></Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title={`在档（未满 ${retentionMonths} 个月）`}
              value={stats?.in_archive ?? total}
              valueStyle={{ color: token.colorWarning }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card size="small">
            <Statistic
              title={`已满 ${retentionMonths} 个月（仅统计）`}
              value={stats?.archived ?? 0}
              valueStyle={{ color: token.colorTextTertiary }}
            />
          </Card>
        </Col>
      </Row>

      {/* 视图切换 + 工种 Tab + 搜索 */}
      <Card style={{ marginBottom: token.marginLG }}>
        <Space wrap style={{ marginBottom: token.marginMD }}>
          <Button
            type={scope === 'active' ? 'primary' : 'default'}
            onClick={() => setParams({ scope: 'active', page: '1' })}
          >
            在档离职人员
          </Button>
          <Tooltip title="离职已满保留期，档案仅保留统计；系统已提醒超级管理员删除其登录账号">
            <Button
              type={scope === 'archived' ? 'primary' : 'default'}
              onClick={() => setParams({ scope: 'archived', page: '1' })}
            >
              已满{retentionMonths}个月（待清理）{stats?.archived ? ` · ${stats.archived}` : ''}
            </Button>
          </Tooltip>
        </Space>

        <Space wrap style={{ marginBottom: token.marginMD }}>
          {tabOptions.map((t) => (
            <Button
              key={t.key}
              type={activeTab === t.key ? 'primary' : 'default'}
              onClick={() => { setParams({ tab: t.key, page: '1' }); }}
            >
              {t.label}
            </Button>
          ))}
        </Space>

        <Space.Compact style={{ width: '100%' }}>
          <Input
            id="staff-rest-search"
            placeholder="搜索工号或姓名..."
            value={searchInputValue}
            onChange={handleSearchChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            onPressEnter={handleSearch}
            allowClear
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </Space.Compact>
      </Card>

      {scope === 'archived' && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: token.marginMD }}
          message="以下人员离职已满保留期"
          description={`其档案仅保留统计。系统已通过站内信提醒超级管理员手动删除登录账号（删除账号会一并清理人员档案）。`}
        />
      )}

      {loading ? (
        <Flex justify="center" style={{ padding: token.paddingLG * 3 }}><Spin size="large" /></Flex>
      ) : staffList.length === 0 ? (
        <Flex justify="center" style={{ padding: token.paddingLG * 3, color: token.colorTextTertiary }}>
          {scope === 'archived' ? '暂无已满保留期的离职人员' : '暂无在档离职人员'}
        </Flex>
      ) : (
        <>
          <Row gutter={[token.marginMD, token.marginMD]}>
            {staffList.map((item) => (
              <Col key={item.employee_id} {...colSpan}>
                <Card style={{ opacity: 0.9 }} styles={{ body: { padding: 0 } }}>
                  <div style={{ display: 'flex', alignItems: 'stretch' }}>
                    {/* 照片 */}
                    <div style={{ width: 96, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: token.paddingSM, background: token.colorFillQuaternary }}>
                      {(item.side_photo || item.front_photo) ? (
                        <SafeImage src={item.side_photo || item.front_photo} alt={item.name}
                          style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover', filter: 'grayscale(1)' }} />
                      ) : (
                        <div style={{ width: 56, height: 56, borderRadius: '50%', backgroundColor: token.colorFillSecondary, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: token.fontSizeHeading3, color: token.colorWhite }}>
                          {item.name[0]}
                        </div>
                      )}
                    </div>
                    {/* 信息 */}
                    <div style={{ flex: 1, padding: token.paddingSM, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minWidth: 0 }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: token.marginXS, marginBottom: token.marginXS, flexWrap: 'wrap' }}>
                          <Text strong style={{ color: token.colorText }}>{item.name}</Text>
                          <Tag color={WORK_TYPE_COLOR[item.work_type] || 'default'} style={{ fontSize: token.fontSizeSM, lineHeight: '18px' }}>{WORK_TYPE_LABELS[item.work_type] || item.work_type}</Tag>
                          <Tag color="red" style={{ fontSize: token.fontSizeSM, lineHeight: '18px' }}>已离职</Tag>
                        </div>
                        <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{item.employee_id}</Text>
                        {item.department && (
                          <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block' }}>
                            <TeamOutlined /> {item.department}
                          </Text>
                        )}
                        {/* [新增 2026-09-11] 离职时间与原因 */}
                        <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block' }}>
                          离职时间：{item.resigned_at ? formatDateTime(item.resigned_at) : '（历史数据未记录）'}
                        </Text>
                        {item.resign_reason && (
                          <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block' }} ellipsis={{ tooltip: item.resign_reason }}>
                            原因：{item.resign_reason}
                          </Text>
                        )}
                      </div>
                      <Space size={token.marginXS} style={{ marginTop: token.marginXS }} wrap>
                        <Button size="small" onClick={() => navigate(`/staff/${item.employee_id}`, { state: { returnTo: location.pathname + location.search } })}>查看详情</Button>
                        {canRestore && scope === 'active' && (
                          <Button size="small" type="primary" onClick={() => handleRestore(item)}>恢复在职</Button>
                        )}
                        {scope === 'archived' && (
                          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => navigate('/users')}>
                            去删除登录账号
                          </Button>
                        )}
                      </Space>
                    </div>
                  </div>
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

export default StaffRestArea;
