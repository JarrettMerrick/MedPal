import React, { useState, useEffect } from 'react';
import { Table, Button, Input, Select, Space, Tag, message, Popconfirm, Tooltip } from 'antd';
import { PlusOutlined, SearchOutlined, DeleteOutlined, EditOutlined, EyeOutlined, CopyOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getSignageList, deleteSignage } from '../../api/signage';
import type { Signage } from '../../api/signage';
import { getSignageCategories } from '../../api/signage-settings';
import { campusApi } from '../../api/campus';
import type { Campus, Building, Floor } from '../../types/campus';
import { hasPermission, PERM_SIGNAGE_CREATE, PERM_SIGNAGE_EDIT, PERM_SIGNAGE_DELETE } from '../../utils/permissions';
import { useAuth } from '../../contexts/AuthContext';
// [修复 2026-09-09] 复用统一状态常量：此前私有 STATUS_MAP 缺 repair_in_progress，
// 导致列表状态列显示英文原值、且状态筛选下拉缺少「维修处理中」
import { SIGNAGE_STATUS_MAP, SIGNAGE_STATUS_OPTIONS } from '../../constants/signageStatus';
// [新增 2026-09-14] 剪贴板复制（兼容院内网 http 访问环境）
import { copyText } from '../../utils/clipboard';

const { Option } = Select;

const SignageList: React.FC = () => {
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

  const handleDelete = async (id: number) => {
    try {
      await deleteSignage(id);
      message.success('删除成功');
      fetchData();
    } catch {
      message.error('删除失败');
    }
  };

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
    { title: '名称', dataIndex: 'name', key: 'name', width: 200, ellipsis: true },
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
      title: '操作', key: 'action', width: 180,
      render: (_: unknown, record: Signage) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/signages/${record.id}`)}>查看</Button>
          {hasPermission(user, PERM_SIGNAGE_EDIT) && (
            <Button size="small" icon={<EditOutlined />} onClick={() => navigate(`/signages/edit/${record.id}`)}>编辑</Button>
          )}
          {hasPermission(user, PERM_SIGNAGE_DELETE) && (
            <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
              <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </Space>
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
            options={floorOptions.map((f) => ({
              value: f.floor_name ? `${f.floor_number}F-${f.floor_name}` : `${f.floor_number}F`,
              label: `${f.floor_number}F${f.floor_name ? `-${f.floor_name}` : ''}`,
            }))}
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
