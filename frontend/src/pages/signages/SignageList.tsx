import React, { useState, useEffect } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import { App, Table, Button, Input, Select, Space, Tag, Tooltip } from 'antd';
// [调整 2026-09-17] 移除 EditOutlined / DeleteOutlined / Popconfirm：
// 列表操作列只保留「查看」，编辑与删除入口分别由详情页、编辑页提供
import { PlusOutlined, SearchOutlined, EyeOutlined, CopyOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getSignageList } from '../../api/signage';
import type { Signage } from '../../api/signage';
import { getSignageCategories } from '../../api/signage-settings';
import { campusApi } from '../../api/campus';
import type { Campus, Building, Floor } from '../../types/campus';
// [调整 2026-09-17] 列表只保留「新增标识」权限判断（signage.create）
import { hasPermission, PERM_SIGNAGE_CREATE } from '../../utils/permissions';
import { useAuth } from '../../contexts/AuthContext';
// [修复 2026-09-09] 复用统一状态常量：此前私有 STATUS_MAP 缺 repair_in_progress，
// 导致列表状态列显示英文原值、且状态筛选下拉缺少「维修处理中」
import { SIGNAGE_STATUS_MAP, SIGNAGE_STATUS_OPTIONS } from '../../constants/signageStatus';
// [新增 2026-09-14] 剪贴板复制（兼容院内网 http 访问环境）
import { copyText } from '../../utils/clipboard';
// [调整 2026-09-17] 楼层展示统一走 utils/floor（楼层号已为 F3/B1 字母编号）
import { floorLabel } from '../../utils/floor';

const { Option } = Select;

const SignageList: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<Signage[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  // [新增 2026-09-07] 院区/楼栋/楼层筛选（与表单一致的三级级联，取值格式与标识存储口径相同）
  const [campus, setCampus] = useState<string | undefined>();
  const [building, setBuilding] = useState<string | undefined>();
  const [floor, setFloor] = useState<string | undefined>();
  // [修复 2026-09-07] 分类筛选选项从「标识分类设置」动态获取，而非硬编码
  const [categoryOptions, setCategoryOptions] = useState<string[]>([]);
  const [campusOptions, setCampusOptions] = useState<Campus[]>([]);
  const [buildingOptions, setBuildingOptions] = useState<Building[]>([]);
  const [floorOptions, setFloorOptions] = useState<Floor[]>([]);

  // [修复 2026-09-07] 加载分类设置中的分类名称作为筛选下拉项
  useEffect(() => {
    getSignageCategories({ page: 1, page_size: 200 })
      .then((r) => setCategoryOptions(r.items.map((c) => c.name)))
      .catch(() => { /* 加载失败时下拉留空，不影响列表展示 */ });
  }, []);

  // [新增 2026-09-07] 加载院区选项
  useEffect(() => {
    campusApi.getAllCampuses()
      .then((list) => setCampusOptions(list || []))
      .catch(() => { /* 加载失败时下拉留空 */ });
  }, []);

  const campusId = campusOptions.find((c) => c.name === campus)?.id;

  // [新增 2026-09-07] 院区变化时加载楼栋选项，并重置下级筛选
  useEffect(() => {
    setBuilding(undefined);
    setFloor(undefined);
    setBuildingOptions([]);
    setFloorOptions([]);
    if (!campusId) return;
    campusApi.getBuildings(campusId, 1, 200)
      .then((r) => setBuildingOptions(r.items || []))
      .catch(() => { /* 加载失败时下拉留空 */ });
  }, [campusId]);

  const buildingId = buildingOptions.find(
    (b) => `${b.building_number}-${b.name}` === building,
  )?.id;

  // [新增 2026-09-07] 楼栋变化时加载楼层选项，并重置楼层筛选
  useEffect(() => {
    setFloor(undefined);
    setFloorOptions([]);
    if (!buildingId) return;
    campusApi.getFloors(buildingId, 1, 200)
      .then((r) => setFloorOptions(r.items || []))
      .catch(() => { /* 加载失败时下拉留空 */ });
  }, [buildingId]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await getSignageList({ page, page_size: pageSize, search, category, status, campus, building, floor });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error('获取标识列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [page, pageSize, category, status, campus, building, floor]);

  /** [新增 2026-09-14] 一键复制标识编码：巡检/报修时需频繁转述编码，避免手动选中复制出错 */
  const handleCopyCode = async (code: string) => {
    const ok = await copyText(code);
    if (ok) message.success(`已复制编码：${code}`);
    else message.error('复制失败，请手动选中复制');
  };

  const columns = [
    {
      // [调整 2026-09-14] 编码列增加一键复制按钮（列宽由 120 放宽以容纳图标）
      title: '编码', dataIndex: 'code', key: 'code', width: 158,
      render: (code: string) => (
        <Space size={2}>
          <span>{code}</span>
          <Tooltip title="复制编码">
            <Button
              type="text"
              size="small"
              icon={<CopyOutlined />}
              onClick={() => handleCopyCode(code)}
              aria-label={`复制编码 ${code}`}
            />
          </Tooltip>
        </Space>
      ),
    },
    // [调整 2026-09-19] 「名称」去掉固定宽度与 ellipsis，改为自适应 + 允许换行。
    // 本表原 8 列全部定宽（合计 958px），无列可伸缩 → 窄屏会横向滚动。
    // 标识名称是全表最长的文本列，交由它吸收剩余空间；同时不再截断为省略号，
    // 长名称完整折行展示（与「院区管理」等页面的处理口径一致）。
    {
      title: '名称', dataIndex: 'name', key: 'name',
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 160 } as React.CSSProperties,
      }),
    },
    { title: '分类', dataIndex: 'category', key: 'category', width: 100 },
    { title: '院区', dataIndex: 'campus', key: 'campus', width: 80 },
    // [显示 2026-09-03] 楼栋列显示"楼栋号-楼栋名称"，增加宽度
    { title: '楼栋', dataIndex: 'building', key: 'building', width: 120, ellipsis: true },
    // [显示 2026-09-03] 楼层列显示"楼层号F-楼层名称"，增加宽度
    { title: '楼层', dataIndex: 'floor', key: 'floor', width: 100, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => {
        const s = SIGNAGE_STATUS_MAP[v] || { label: v, color: 'default' };
        return <Tag color={s.color}>{s.label}</Tag>;
      },
    },
    {
      // [调整 2026-09-17] 操作列只保留「查看」：
      //   - 「编辑」入口统一由标识详情页提供（查看 → 编辑），列表不再重复放置；
      //   - 「删除」入口移至标识编辑页（查看 → 编辑 → 删除），避免在列表中误删。
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, record: Signage) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/signages/${record.id}`)}>查看</Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Space wrap>
          {/* [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警 */}
          <Input id="signage-search" placeholder="搜索编码/名称" value={search} onChange={(e) => setSearch(e.target.value)}
            onPressEnter={fetchData} style={{ width: 200 }} suffix={<SearchOutlined onClick={fetchData} />} />
          {/* [新增 2026-09-07] 院区/楼栋/楼层三级级联筛选；取值格式与标识存储口径一致（楼栋=楼栋号-名称，楼层=楼层号F-名称） */}
          <Select
            id="signage-filter-campus"
            placeholder="院区" allowClear showSearch optionFilterProp="label"
            style={{ width: 150 }} value={campus}
            onChange={(v) => { setCampus(v); setPage(1); }}
            options={campusOptions.map((c) => ({ value: c.name, label: c.name }))}
          />
          <Select
            id="signage-filter-building"
            placeholder="楼栋" allowClear showSearch optionFilterProp="label"
            style={{ width: 170 }} value={building}
            disabled={!campus}
            onChange={(v) => { setBuilding(v); setPage(1); }}
            options={buildingOptions.map((b) => ({
              value: `${b.building_number}-${b.name}`,
              label: `${b.building_number}-${b.name}`,
            }))}
          />
          <Select
            id="signage-filter-floor"
            placeholder="楼层" allowClear showSearch optionFilterProp="label"
            style={{ width: 150 }} value={floor}
            disabled={!building}
            onChange={(v) => { setFloor(v); setPage(1); }}
            options={floorOptions.map((f) => {
              // [调整 2026-09-17] 选项值与展示统一为 floorLabel（如 F3-门诊层），
              // 与标识存储的 floor 文本口径一致，避免筛选项与数据对不上
              const label = floorLabel(f);
              return { value: label, label };
            })}
          />
          <Select placeholder="分类" allowClear style={{ width: 120 }} value={category} onChange={(v) => { setCategory(v); setPage(1); }}>
            {categoryOptions.map((c) => <Option key={c} value={c}>{c}</Option>)}
          </Select>
          <Select placeholder="状态" allowClear style={{ width: 120 }} value={status} onChange={(v) => { setStatus(v); setPage(1); }}>
            {/* [修复 2026-09-09] 筛选项改用统一常量，补上「维修处理中」 */}
            {SIGNAGE_STATUS_OPTIONS.map((s) => <Option key={s.value} value={s.value}>{s.label}</Option>)}
          </Select>
        </Space>
        {hasPermission(user, PERM_SIGNAGE_CREATE) && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/signages/new')}>新增标识</Button>
        )}
      </div>
      <Table columns={columns} dataSource={data} rowKey="id" loading={loading}
        pagination={{ current: page, pageSize, total, onChange: (p, ps) => { setPage(p); setPageSize(ps); } }} />
    </div>
  );
};

export default SignageList;
