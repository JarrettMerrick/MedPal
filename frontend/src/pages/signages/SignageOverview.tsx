// [新增 2026-09-09] 标识总览页（点击「标识平面」进入）：
// KPI 指标卡 / 分类·院区·楼栋分布 / 维修概况 / 巡检趋势（自定义区间，最多90天）/ 最近动态
// 实时更新：60 秒轮询（页面不可见时跳过）+ 手动刷新 + 最后更新时间
import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, Row, Col, Statistic, Button, Spin, Empty, Tag, List, Space, Typography, DatePicker, message,
} from 'antd';
import {
  ReloadOutlined, AlertOutlined, MobileOutlined, ApartmentOutlined, ToolOutlined, TagsOutlined,
} from '@ant-design/icons';
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, LineChart, Line,
} from 'recharts';
import dayjs, { type Dayjs } from 'dayjs';
import { useNavigate } from 'react-router-dom';
import {
  getSignageOverview, getInspectionTrend,
} from '../../api/signage';
import type { SignageOverviewData, InspectionTrendItem } from '../../api/signage';
import { hasPermission, PERM_SIGNAGE_MARKER, PERM_SIGNAGE_INSPECTION, PERM_SIGNAGE_ALERT } from '../../utils/permissions';
import { useAuth } from '../../contexts/AuthContext';
import { formatDateTimeStandard } from '../../utils/time';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

// 图表配色（与系统主色系一致）
const PIE_COLORS = ['#2F9E64', '#EAB308', '#DC2626', '#1677FF', '#6B7280'];
const MAX_TREND_DAYS = 90;
const POLL_INTERVAL_MS = 60_000;

const SignageOverview: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<SignageOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string>('');
  const [trend, setTrend] = useState<InspectionTrendItem[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()]);

  // 拉取总览聚合数据
  const fetchOverview = useCallback(async () => {
    try {
      const r = await getSignageOverview();
      setData(r);
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch {
      message.error('获取标识总览数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // 拉取巡检趋势（自定义日期区间，最多 90 天）
  const fetchTrend = useCallback(async (start: Dayjs, end: Dayjs) => {
    setTrendLoading(true);
    try {
      const r = await getInspectionTrend({
        start_date: start.format('YYYY-MM-DD'),
        end_date: end.format('YYYY-MM-DD'),
      });
      setTrend(r.items);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '获取巡检趋势失败');
    } finally {
      setTrendLoading(false);
    }
  }, []);

  useEffect(() => { fetchOverview(); }, [fetchOverview]);

  // [需求] 60 秒轮询自动刷新；页面不可见时跳过请求
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') fetchOverview();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [fetchOverview]);

  useEffect(() => { fetchTrend(range[0], range[1]); }, [range, fetchTrend]);

  // 日期区间变更：禁止未来日期与超过 90 天
  const handleRangeChange = (dates: null | (Dayjs | null)[]) => {
    if (!dates || !dates[0] || !dates[1]) return;
    if (dates[1].diff(dates[0], 'day') + 1 > MAX_TREND_DAYS) {
      message.warning(`最多可查询 ${MAX_TREND_DAYS} 天数据`);
      return;
    }
    setRange([dates[0], dates[1]]);
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!data) return <Empty description="暂无标识总览数据" />;

  const { kpi, repair_summary } = data;

  // KPI 卡片（点击跳转对应页面）
  const kpiCards: { title: string; value: number; color: string; onClick?: () => void }[] = [
    { title: '标识总数', value: kpi.total, color: '#1F2933', onClick: () => navigate('/signages') },
    { title: '正常', value: kpi.normal, color: '#2F9E64', onClick: () => navigate('/signages') },
    { title: '轻微破损', value: kpi.damaged, color: '#EAB308', onClick: () => navigate('/signages') },
    { title: '严重损坏', value: kpi.severely_damaged, color: '#DC2626', onClick: () => navigate('/signages') },
    { title: '维修处理中', value: kpi.repair_in_progress, color: '#1677FF', onClick: () => navigate('/signage-repairs') },
    { title: '已拆除', value: kpi.removed, color: '#6B7280', onClick: () => navigate('/signages') },
    { title: '巡检临期(7天内)', value: kpi.inspection_due_soon, color: '#FAAD14', onClick: () => navigate('/signage-alerts') },
    { title: '巡检已超期', value: kpi.inspection_overdue, color: '#FF4D4F', onClick: () => navigate('/signage-alerts') },
  ];

  const statusPie = [
    { name: '正常', value: kpi.normal },
    { name: '轻微破损', value: kpi.damaged },
    { name: '严重损坏', value: kpi.severely_damaged },
    { name: '维修处理中', value: kpi.repair_in_progress },
    { name: '已拆除', value: kpi.removed },
  ].filter((i) => i.value > 0);

  return (
    <div style={{ padding: 16 }}>
      {/* 页头：手动刷新 + 最后更新时间 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Title level={4} style={{ margin: 0 }}>标识总览</Title>
        <Text type="secondary">数据每 60 秒自动刷新{updatedAt ? ` · 最后更新 ${updatedAt}` : ''}</Text>
        <Button size="small" icon={<ReloadOutlined />} onClick={fetchOverview}>刷新</Button>
        <Space style={{ marginLeft: 'auto' }} wrap>
          {hasPermission(user, PERM_SIGNAGE_MARKER) && (
            <Button size="small" icon={<ApartmentOutlined />} onClick={() => navigate('/signage-floorplan')}>标识标记</Button>
          )}
          {hasPermission(user, PERM_SIGNAGE_INSPECTION) && (
            <Button size="small" icon={<MobileOutlined />} onClick={() => navigate('/signage-mobile')}>标识巡检</Button>
          )}
          {hasPermission(user, PERM_SIGNAGE_ALERT) && (
            <Button size="small" icon={<AlertOutlined />} onClick={() => navigate('/signage-alerts')}>标识预警</Button>
          )}
        </Space>
      </div>

      {/* KPI 指标卡 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {kpiCards.map((c) => (
          <Col key={c.title} xs={12} sm={8} md={6} lg={3}>
            <Card
              hoverable
              onClick={c.onClick}
              styles={{ body: { padding: 12 } }}
            >
              <Statistic title={<span style={{ fontSize: 12 }}>{c.title}</span>} value={c.value} valueStyle={{ color: c.color, fontSize: 20 }} />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 分布图：状态饼图 + 分类柱状图 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="标识状态分布">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={statusPie} dataKey="value" nameKey="name" outerRadius={90} label>
                  {statusPie.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="分类分布（Top10）">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.category_distribution.slice(0, 10)}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#1565B8" name="数量" />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {/* 院区分布 + 楼栋 Top10 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="院区分布">
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={data.campus_distribution} dataKey="count" nameKey="name" outerRadius={90} label>
                  {data.campus_distribution.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="楼栋分布 Top10">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.building_top} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#0E4B8C" name="数量" />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {/* 维修概况 */}
      <Card title="维修概况" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]}>
          <Col xs={12} md={6}><Statistic title="本月发起维修" value={repair_summary.month_started} /></Col>
          <Col xs={12} md={6}><Statistic title="本月完成维修" value={repair_summary.month_completed} /></Col>
          <Col xs={12} md={6}><Statistic title="维修处理中" value={repair_summary.in_progress} valueStyle={{ color: '#1677FF' }} /></Col>
          <Col xs={12} md={6}><Statistic title="平均维修时长(小时)" value={repair_summary.avg_hours} /></Col>
        </Row>
        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Tag icon={<ToolOutlined />} color="blue">供应商维修 {repair_summary.party_vendor} 次</Tag>
          <Tag icon={<ToolOutlined />} color="cyan">工程部维修 {repair_summary.party_engineering} 次</Tag>
        </div>
      </Card>

      {/* 巡检趋势（自定义日期区间，最多 90 天） */}
      <Card
        title="巡检提交量趋势"
        extra={(
          <RangePicker
            value={range}
            allowClear={false}
            onChange={handleRangeChange}
            disabledDate={(d) => d && d > dayjs().endOf('day')}
          />
        )}
        style={{ marginBottom: 16 }}
      >
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={24} />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Line type="monotone" dataKey="count" stroke="#1565B8" name="巡检数" dot={false} />
          </LineChart>
        </ResponsiveContainer>
        {trendLoading && <div style={{ textAlign: 'center', padding: 8 }}><Spin size="small" /></div>}
      </Card>

      {/* 最近动态：维修 / 巡检 / 预警 */}
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={8}>
          <Card title="最近维修" size="small">
            <List
              size="small"
              dataSource={data.recent_repairs}
              locale={{ emptyText: '暂无维修记录' }}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/signages/${item.signage_id}`)}
                >
                  <List.Item.Meta
                    title={<span style={{ fontSize: 13 }}>{item.code} {item.name}</span>}
                    description={
                      <span style={{ fontSize: 12, color: '#5B6B7B' }}>
                        {item.party_label}{item.supplier_name ? `（${item.supplier_name}）` : ''}
                        {' · '}{item.started_at ? formatDateTimeStandard(item.started_at) : '-'}
                      </span>
                    }
                  />
                  <Tag color={item.status === 'completed' ? 'green' : 'processing'}>
                    {item.status === 'completed' ? '已完成' : '处理中'}
                  </Tag>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="最近巡检" size="small">
            <List
              size="small"
              dataSource={data.recent_inspections}
              locale={{ emptyText: '暂无巡检记录' }}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/signages/${item.signage_id}`)}
                >
                  <List.Item.Meta
                    title={<span style={{ fontSize: 13 }}>{item.code} {item.name}</span>}
                    description={
                      <span style={{ fontSize: 12, color: '#5B6B7B' }}>
                        {item.result_label} · {item.inspector || '未知'}
                        {' · '}{item.created_at ? formatDateTimeStandard(item.created_at) : '-'}
                      </span>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="最新预警" size="small">
            <List
              size="small"
              dataSource={data.recent_alerts}
              locale={{ emptyText: '暂无预警' }}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/signages/${item.id}`)}
                >
                  <List.Item.Meta
                    avatar={<TagsOutlined />}
                    title={<span style={{ fontSize: 13 }}>{item.code} {item.name}</span>}
                    description={<span style={{ fontSize: 12, color: '#5B6B7B' }}>{item.type} · {item.info}</span>}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default SignageOverview;
