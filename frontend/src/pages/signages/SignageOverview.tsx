// [新增 2026-09-09] 标识总览页（点击「标识平面」进入）：
// KPI 指标卡 / 分类·院区·楼栋分布 / 维修概况 / 巡检趋势（自定义区间，最多90天）/ 最近动态
// 实时更新：60 秒轮询（页面不可见时跳过）+ 手动刷新 + 最后更新时间
import React, { useCallback, useEffect, useState } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Card, Row, Col, Statistic, Button, Spin, Empty, Tag, List, Space, Typography, DatePicker,
  // [改造 2026-09-21] 分布图的维度切换控件
  Segmented,
} from 'antd';
import {
  ReloadOutlined, MobileOutlined, ApartmentOutlined, ToolOutlined, TagsOutlined,
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
// [调整 2026-09-17] 移除 PERM_SIGNAGE_ALERT（「标识预警」入口已下线）
import { hasPermission, PERM_SIGNAGE_MARKER, PERM_SIGNAGE_INSPECTION } from '../../utils/permissions';
import { useAuth } from '../../contexts/AuthContext';
import { formatDateTimeStandard } from '../../utils/time';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

// 图表配色：语义色（正常/破损/严重/处理中）+ 品牌主色
// [调整 2026-09-21] 移除 #1677FF（Ant Design 默认蓝）—— 与本系统主色系无关，
// 是页面配色"杂"的来源之一。第 4 位改为品牌青蓝（深色模式下自动切换）。
const PIE_COLORS = ['#2F9E64', '#EAB308', '#DC2626', '#0E7F8A', '#6B7280'];
const MAX_TREND_DAYS = 90;
const POLL_INTERVAL_MS = 60_000;

const SignageOverview: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<SignageOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<string>('');
  const [trend, setTrend] = useState<InspectionTrendItem[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()]);
  // [改造 2026-09-21] 「分布明细」的维度切换：按分类 / 按院区 / 按楼栋。
  // 原先这三个维度是三张独立的卡片平铺，信息同质且把页面拉长近一半；
  // 合并为一张卡片后用 Segmented 切换，与项目其余页面的分段控件风格一致。
  const [dim, setDim] = useState<'category' | 'campus' | 'building'>('category');

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
  // [改造 2026-09-21] 由 5 个收敛为 4 个，并改用 lg={6}（一行正好 4 个）。
  //
  // 原实现有 5 个卡片却沿用 lg={3}（8 列栅格）—— 一行只占 5/8，**右侧空出 3/8 空白**，
  // 这是页面"不整齐"最直观的来源：2026-09-17 删掉 3 个 KPI 时，栅格没有跟着调整。
  //
  // 数量定为 4 个，依据同类产品的通行做法：
  //   · Ant Design Pro「分析页」= 4 个指标卡（lg={6}，一行铺满）
  //   · Datadog 仪表盘的「黄金四指标」范式 = 4 个
  //   · Grafana stat 面板普遍控制在 3~5 个
  //
  // 「轻微破损 / 严重损坏」合并为「待处理异常」：两者的共同点都是"需要发起维修"，
  // 分开陈列只会让两个数字互相争夺注意力；合并后语义更明确（= 待办量）。
  const kpiCards: { title: string; value: number; color: string; onClick?: () => void }[] = [
    { title: '标识总数', value: kpi.total, color: 'var(--text-1)', onClick: () => navigate('/signages') },
    { title: '正常', value: kpi.normal, color: '#2F9E64', onClick: () => navigate('/signages') },
    {
      title: '待处理异常',
      value: kpi.damaged + kpi.severely_damaged,
      color: '#DC2626',
      onClick: () => navigate('/signage-repairs'),
    },
    // [调整 2026-09-21] 色值 #1677FF（Ant Design 默认蓝）→ 品牌青蓝：
    // 原色与本系统主色系无关，是页面配色杂乱的来源之一
    { title: '维修处理中', value: kpi.repair_in_progress, color: 'var(--accent)', onClick: () => navigate('/signage-repairs') },
    // [删除 2026-09-17] 按需求移除「已拆除」KPI（总览不再展示已拆除标识）
    // [删除 2026-09-17] 移除「巡检临期(7天内)」「巡检已超期」KPI：
    // 「标识预警」页已下线，这两项预警口径无对应页面可跳转
  ];

  const statusPie = [
    { name: '正常', value: kpi.normal },
    { name: '轻微破损', value: kpi.damaged },
    { name: '严重损坏', value: kpi.severely_damaged },
    { name: '维修处理中', value: kpi.repair_in_progress },
    // [删除 2026-09-17] 按需求移除「已拆除」（总览状态分布不再包含已拆除标识）
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
          {/* [删除 2026-09-17] 移除「标识预警」入口：「标识预警」页已下线，能力并入「标识维修」 */}
        </Space>
      </div>

      {/* KPI 指标卡 */}
      {/* [改造 2026-09-21] 栅格 lg={3} → lg={6}：4 个卡片正好铺满一行，消除右侧 3/8 空白。
          间距 12 → 16 与全站卡片间距标准一致；数字 20px → 24px（KPI 的首要职责是"一眼读清数值"）。 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {kpiCards.map((c) => (
          <Col key={c.title} xs={12} md={6}>
            <Card
              hoverable
              onClick={c.onClick}
              styles={{ body: { padding: 16 } }}
            >
              <Statistic
                title={<span style={{ fontSize: 12 }}>{c.title}</span>}
                value={c.value}
                valueStyle={{ color: c.color, fontSize: 24 }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 分布图：[改造 2026-09-21] 4 张同质图表 → 「状态分布（独立）+ 分布明细（维度切换）」
          原先是 4 张平铺的分布图（状态 / 分类 / 院区 / 楼栋），占掉页面近一半高度，
          而它们表达的是同一类信息（"什么占多少"），信息重复度高、缺少主次。
          现按同类产品（Grafana / Datadog 仪表盘）的通行做法改为「一张图 + 维度切换」：
            · 「标识状态分布」独立成卡 —— 它含异常量，是最需要一眼看到的一张；
            · 分类 / 院区 / 楼栋 三个维度合并进同一张卡，用 Segmented 切换。
          页面中部由「两行四卡」压缩为「一行两卡」，长度显著缩短且不丢信息。 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={10}>
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
        <Col xs={24} lg={14}>
          <Card
            title={
              dim === 'category' ? '分类分布（Top10）'
                : dim === 'campus' ? '院区分布'
                  : '楼栋分布（Top10）'
            }
            extra={
              <Segmented
                size="small"
                value={dim}
                onChange={(v) => setDim(v as 'category' | 'campus' | 'building')}
                options={[
                  { label: '按分类', value: 'category' },
                  { label: '按院区', value: 'campus' },
                  { label: '按楼栋', value: 'building' },
                ]}
              />
            }
          >
            <ResponsiveContainer width="100%" height={260}>
              {dim === 'building' ? (
                <BarChart data={data.building_top} layout="vertical" margin={{ left: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="var(--accent)" name="数量" />
                </BarChart>
              ) : dim === 'campus' ? (
                <PieChart>
                  <Pie data={data.campus_distribution} dataKey="count" nameKey="name" outerRadius={90} label>
                    {data.campus_distribution.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              ) : (
                <BarChart data={data.category_distribution.slice(0, 10)}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} interval={0} angle={-20} textAnchor="end" height={60} />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" fill="var(--accent)" name="数量" />
                </BarChart>
              )}
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {/* 维修概况 */}
      <Card title="维修概况" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}><Statistic title="本月发起维修" value={repair_summary.month_started} /></Col>
          <Col xs={12} md={6}><Statistic title="本月完成维修" value={repair_summary.month_completed} /></Col>
          {/* [调整 2026-09-21] 色值 #1677FF（Ant Design 默认蓝）→ 品牌青蓝 */}
          <Col xs={12} md={6}><Statistic title="维修处理中" value={repair_summary.in_progress} valueStyle={{ color: 'var(--accent)' }} /></Col>
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
            <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={24} />
            <YAxis allowDecimals={false} />
            <Tooltip />
            {/* [调整 2026-09-21] #1565B8（外来蓝）→ 品牌青蓝 */}
            <Line type="monotone" dataKey="count" stroke="var(--accent)" name="巡检数" dot={false} />
          </LineChart>
        </ResponsiveContainer>
        {trendLoading && <div style={{ textAlign: 'center', padding: 8 }}><Spin size="small" /></div>}
      </Card>

      {/* 最近动态：维修 / 巡检 / 预警 */}
      {/* [改造 2026-09-21] 三栏宽度由 8/8/8 调整为 7/7/10：
          「最新预警」是本页唯一**可操作**的信息（点进去能处理），
          原先它与两个只读动态流等宽、视觉权重相同，重要信息被埋没。
          加宽后它在三栏中明显更醒目，形成"数据 → 行动"的收尾。
          （若要进一步把它提到最前，需要调整三个 Card 的顺序，改动更大，可按需再做。） */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={7}>
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
                      <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
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
        <Col xs={24} lg={7}>
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
                      <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
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
        <Col xs={24} lg={10}>
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
                    description={<span style={{ fontSize: 12, color: 'var(--text-2)' }}>{item.type} · {item.info}</span>}
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
