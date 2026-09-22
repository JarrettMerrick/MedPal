// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 院区-楼栋-楼层-区域管理页。
 *
 * [重构 2026-09-17] 布局由「三列 + 右列上下堆叠楼层/区域」改为**四栏级联**（Miller Columns）：
 * - 院区 / 楼栋 / 楼层 / 区域四栏**等宽等高、结构完全对称**：
 *   Row 使用 align="stretch" + 卡片 height:100%（顶边/底边对齐），
 *   标题行、父级提示行、搜索行高度固定（列表起点对齐），
 *   列表区 min-height 一致且超出滚动（列表高度对齐）；
 * - 每栏顶部提供搜索框（数据已全量载入，前端即时过滤），依次选择上级即刷新下一栏；
 * - 列表项改为紧凑行：名称 + 次要信息 + 「已禁用」标记，编辑/删除在悬停时出现
 *   （触屏设备无 hover，操作按钮常显，避免无法编辑）；
 * - 院区列表项**不再展示地址与楼栋数**（按需求精简），地址仍在编辑弹窗中维护；
 * - 空状态区分「未选择上级」与「暂无数据」，避免四栏出现无意义空白。
 *
 * 响应式：≥1200px 四栏并排 / 768–1199px 两栏 / <768px 单栏（antd 栅格自动降级）。
 * 业务逻辑（增删改查、校验、错误提示、级联重置）与原实现保持一致。
 */

import React, { useEffect, useMemo, useState } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Button, Card, Col, Form, Input, Modal, Popconfirm, Row,
  Select, Switch, Tooltip, Typography,
} from 'antd';
import {
  ApartmentOutlined, AppstoreOutlined, BorderOutlined, DeleteOutlined,
  EditOutlined, HomeOutlined, PlusOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons';

import { campusApi } from '../../api/campus';
import type { Area, Building, Campus, Floor } from '../../types/campus';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
// [新增 2026-09-17] 楼层号规范：地上 F1/F2…、地下 B1/B2…
import { floorLabel, normalizeFloorNumber, FLOOR_NUMBER_HINT } from '../../utils/floor';

const { Text } = Typography;
const { Option } = Select;

/** 区域类型中文名（列表项次要信息用） */
const AREA_TYPE_TEXT: Record<string, string> = {
  east: '东区',
  west: '西区',
  merged: '合并区域',
};

/* ------------------------------------------------------------------ */
/* 级联栏骨架（四栏共用，保证结构对称与等高）                            */
/* ------------------------------------------------------------------ */

interface CascadeColumnProps {
  icon: React.ReactNode;
  title: string;
  /** 当前展示条数 / 总数（搜索中显示 "n / 总数"） */
  shown: number;
  total: number;
  /** 已选上级名称；为空表示尚未选择 */
  parentName?: string;
  /** 未选择上级时的引导文案 */
  parentHint: string;
  addLabel: string;
  onAdd: () => void;
  addDisabled?: boolean;
  keyword: string;
  onKeywordChange: (v: string) => void;
  searchPlaceholder: string;
  emptyWhenNoParent: string;
  emptyWhenNoData: string;
  hasItems: boolean;
  children: React.ReactNode;
}

const CascadeColumn: React.FC<CascadeColumnProps> = ({
  icon, title, shown, total, parentName, parentHint, addLabel, onAdd, addDisabled,
  keyword, onKeywordChange, searchPlaceholder, emptyWhenNoParent, emptyWhenNoData,
  hasItems, children,
}) => (
  <Card className="campus-cascade__card" size="small">
    {/* 栏头：图标 + 名称 + 计数 + 新增（高度固定，四栏对齐） */}
    <div className="campus-cascade__head">
      <span className="campus-cascade__icon">{icon}</span>
      <span className="campus-cascade__title">{title}</span>
      <span className="campus-cascade__count">
        {shown === total ? `共 ${total}` : `${shown} / ${total}`}
      </span>
      <span className="campus-cascade__head-extra">
        <Tooltip title={addDisabled ? '请先选择上级' : addLabel}>
          <Button
            type="text"
            size="small"
            icon={<PlusOutlined />}
            onClick={onAdd}
            disabled={addDisabled}
            aria-label={addLabel}
          />
        </Tooltip>
      </span>
    </div>

    {/* 父级提示行（高度固定） */}
    <div className="campus-cascade__parent">
      {parentName ? (
        <>
          <ApartmentOutlined style={{ flexShrink: 0, marginTop: 2 }} />
          {/* [改造 2026-09-19] 移除内联 ellipsis：父级名称需完整展示，超长时随容器自然换行 */}
          <span>{parentName}</span>
        </>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>{parentHint}</Text>
      )}
    </div>

    {/* 搜索行（高度固定） */}
    <div className="campus-cascade__search">
      <Input
        size="small"
        allowClear
        prefix={<SearchOutlined style={{ color: 'var(--text-icon)' }} />}
        placeholder={searchPlaceholder}
        value={keyword}
        onChange={(e) => onKeywordChange(e.target.value)}
      />
    </div>

    {/* 列表区（等高 + 滚动） */}
    <div className="campus-cascade__list">
      {hasItems ? (
        children
      ) : (
        <div className="campus-cascade__empty">
          {parentName ? <AppstoreOutlined /> : <ApartmentOutlined />}
          <span>{parentName ? emptyWhenNoData : emptyWhenNoParent}</span>
        </div>
      )}
    </div>
  </Card>
);

/* ------------------------------------------------------------------ */
/* 列表项（四栏共用）                                                   */
/* ------------------------------------------------------------------ */

interface CascadeItemProps {
  title: string;
  /** 次要信息：代号 / 编号 / 计数 / 类型 */
  meta?: React.ReactNode;
  /** 已禁用（is_active=false）：弱化文字并展示标记 */
  inactive?: boolean;
  selected?: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
  deleteTitle: string;
}

const CascadeItem: React.FC<CascadeItemProps> = ({
  title, meta, inactive, selected, onSelect, onEdit, onDelete, deleteTitle,
}) => (
  <div
    className={`cascade-item${selected ? ' is-selected' : ''}${inactive ? ' is-inactive' : ''}`}
    role="button"
    tabIndex={0}
    aria-pressed={selected}
    onClick={onSelect}
    onKeyDown={(e) => {
      // 键盘可达：Enter / 空格 等同于点击选择
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelect();
      }
    }}
  >
    <div className="cascade-item__main">
      <span className="cascade-item__title" title={title}>{title}</span>
      {inactive && <span className="cascade-item__badge">已禁用</span>}
      <span className="cascade-item__actions">
        <Tooltip title="编辑">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            aria-label="编辑"
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
          />
        </Tooltip>
        <Popconfirm title={deleteTitle} okText="确定" cancelText="取消" onConfirm={onDelete}>
          <Tooltip title="删除">
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              aria-label="删除"
              onClick={(e) => e.stopPropagation()}
            />
          </Tooltip>
        </Popconfirm>
      </span>
    </div>
    {meta && <div className="cascade-item__meta">{meta}</div>}
  </div>
);

/* ------------------------------------------------------------------ */
/* 页面                                                                */
/* ------------------------------------------------------------------ */

const CampusManagement: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  const [campuses, setCampuses] = useState<Campus[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [floors, setFloors] = useState<Floor[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);

  const [selectedCampus, setSelectedCampus] = useState<Campus | null>(null);
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(null);
  const [selectedFloor, setSelectedFloor] = useState<Floor | null>(null);

  // [重构] 分栏 loading：切换上级时只有受影响的栏显示加载态，避免四栏一起闪烁
  const [loadingCampus, setLoadingCampus] = useState(false);
  const [loadingBuilding, setLoadingBuilding] = useState(false);
  const [loadingFloor, setLoadingFloor] = useState(false);
  const [loadingArea, setLoadingArea] = useState(false);

  // [重构] 分栏搜索：数据已全量载入，前端过滤即时响应（无需请求后端）
  const [kwCampus, setKwCampus] = useState('');
  const [kwBuilding, setKwBuilding] = useState('');
  const [kwFloor, setKwFloor] = useState('');
  const [kwArea, setKwArea] = useState('');

  // 模态框状态
  const [campusModalVisible, setCampusModalVisible] = useState(false);
  const [buildingModalVisible, setBuildingModalVisible] = useState(false);
  const [floorModalVisible, setFloorModalVisible] = useState(false);
  const [areaModalVisible, setAreaModalVisible] = useState(false);

  const [editingItem, setEditingItem] = useState<Campus | Building | Floor | Area | null>(null);
  const [campusForm] = Form.useForm();
  const [buildingForm] = Form.useForm();
  const [floorForm] = Form.useForm();
  const [areaForm] = Form.useForm();

  /* ---------------- 数据加载 ---------------- */

  const loadCampuses = async () => {
    try {
      setLoadingCampus(true);
      const response = await campusApi.getCampuses(1, 100);
      setCampuses(response.items);
    } catch {
      message.error('加载院区列表失败');
    } finally {
      setLoadingCampus(false);
    }
  };

  const loadBuildings = async (campusId: number) => {
    try {
      setLoadingBuilding(true);
      const response = await campusApi.getBuildings(campusId, 1, 100);
      setBuildings(response.items);
    } catch {
      message.error('加载楼栋列表失败');
    } finally {
      setLoadingBuilding(false);
    }
  };

  const loadFloors = async (buildingId: number) => {
    try {
      setLoadingFloor(true);
      const response = await campusApi.getFloors(buildingId, 1, 200);
      setFloors(response.items);
    } catch {
      message.error('加载楼层列表失败');
    } finally {
      setLoadingFloor(false);
    }
  };

  const loadAreas = async (floorId: number) => {
    try {
      setLoadingArea(true);
      const response = await campusApi.getAreas(floorId, 1, 200);
      setAreas(response.items);
    } catch {
      message.error('加载区域列表失败');
    } finally {
      setLoadingArea(false);
    }
  };

  useEffect(() => {
    loadCampuses();
  }, []);

  useEffect(() => {
    if (selectedCampus) {
      loadBuildings(selectedCampus.id);
    } else {
      setBuildings([]);
      setFloors([]);
      setAreas([]);
    }
  }, [selectedCampus]);

  useEffect(() => {
    if (selectedBuilding) {
      loadFloors(selectedBuilding.id);
    } else {
      setFloors([]);
      setAreas([]);
    }
  }, [selectedBuilding]);

  useEffect(() => {
    if (selectedFloor) {
      loadAreas(selectedFloor.id);
    } else {
      setAreas([]);
    }
  }, [selectedFloor]);

  /** 页头刷新：同时刷新当前已展开的各层级 */
  const handleRefreshAll = () => {
    loadCampuses();
    if (selectedCampus) loadBuildings(selectedCampus.id);
    if (selectedBuilding) loadFloors(selectedBuilding.id);
    if (selectedFloor) loadAreas(selectedFloor.id);
  };

  /* ---------------- 前端过滤 ---------------- */

  const filteredCampuses = useMemo(() => {
    const kw = kwCampus.trim().toLowerCase();
    if (!kw) return campuses;
    // [重构] 院区搜索匹配名称与代号；不再展示地址，故不参与匹配
    return campuses.filter(
      (c) => c.name.toLowerCase().includes(kw) || (c.code || '').toLowerCase().includes(kw),
    );
  }, [campuses, kwCampus]);

  const filteredBuildings = useMemo(() => {
    const kw = kwBuilding.trim().toLowerCase();
    if (!kw) return buildings;
    return buildings.filter(
      (b) => b.name.toLowerCase().includes(kw) || b.building_number.toLowerCase().includes(kw),
    );
  }, [buildings, kwBuilding]);

  const filteredFloors = useMemo(() => {
    const kw = kwFloor.trim().toLowerCase();
    if (!kw) return floors;
    return floors.filter(
      (f) =>
        (f.floor_name || '').toLowerCase().includes(kw) ||
        // [调整 2026-09-17] 楼层号为字母编号，支持搜 f3 / b1
        (f.floor_number || '').toLowerCase().includes(kw),
    );
  }, [floors, kwFloor]);

  const filteredAreas = useMemo(() => {
    const kw = kwArea.trim().toLowerCase();
    if (!kw) return areas;
    return areas.filter(
      (a) => a.name.toLowerCase().includes(kw) || (AREA_TYPE_TEXT[a.area_type] || '').includes(kw),
    );
  }, [areas, kwArea]);

  /* ---------------- 选择层级 ---------------- */

  const handleSelectCampus = (record: Campus) => {
    setSelectedCampus(record);
    setSelectedBuilding(null);
    setSelectedFloor(null);
    setKwBuilding('');
    setKwFloor('');
    setKwArea('');
  };

  const handleSelectBuilding = (record: Building) => {
    setSelectedBuilding(record);
    setSelectedFloor(null);
    setKwFloor('');
    setKwArea('');
  };

  const handleSelectFloor = (record: Floor) => {
    setSelectedFloor(record);
    setKwArea('');
  };

  /* ---------------- 院区增删改 ---------------- */

  const handleCreateCampus = () => {
    setEditingItem(null);
    campusForm.resetFields();
    campusForm.setFieldsValue({ is_active: true });
    setCampusModalVisible(true);
  };

  const handleEditCampus = (record: Campus) => {
    setEditingItem(record);
    campusForm.setFieldsValue(record);
    setCampusModalVisible(true);
  };

  const handleDeleteCampus = async (id: number) => {
    try {
      await campusApi.deleteCampus(id);
      message.success('删除成功');
      if (selectedCampus?.id === id) {
        setSelectedCampus(null);
      }
      loadCampuses();
    } catch {
      message.error('删除失败');
    }
  };

  const handleCampusSubmit = async () => {
    try {
      const values = await campusForm.validateFields();
      if (editingItem) {
        await campusApi.updateCampus(editingItem.id, values);
        message.success('更新成功');
      } else {
        await campusApi.createCampus(values);
        message.success('创建成功');
      }
      setCampusModalVisible(false);
      loadCampuses();
    } catch {
      message.error('操作失败');
    }
  };

  /* ---------------- 楼栋增删改 ---------------- */

  const handleCreateBuilding = () => {
    setEditingItem(null);
    buildingForm.resetFields();
    buildingForm.setFieldsValue({ is_active: true });
    if (selectedCampus) {
      buildingForm.setFieldsValue({ campus_id: selectedCampus.id });
    }
    setBuildingModalVisible(true);
  };

  const handleEditBuilding = (record: Building) => {
    setEditingItem(record);
    buildingForm.setFieldsValue(record);
    setBuildingModalVisible(true);
  };

  const handleDeleteBuilding = async (id: number) => {
    try {
      await campusApi.deleteBuilding(id);
      message.success('删除成功');
      if (selectedBuilding?.id === id) {
        setSelectedBuilding(null);
      }
      if (selectedCampus) {
        loadBuildings(selectedCampus.id);
      }
    } catch {
      message.error('删除失败');
    }
  };

  const handleBuildingSubmit = async () => {
    try {
      const values = await buildingForm.validateFields();
      if (editingItem) {
        await campusApi.updateBuilding(editingItem.id, values);
        message.success('更新成功');
      } else {
        await campusApi.createBuilding(values);
        message.success('创建成功');
      }
      setBuildingModalVisible(false);
      if (selectedCampus) {
        loadBuildings(selectedCampus.id);
      }
    } catch {
      message.error('操作失败');
    }
  };

  /* ---------------- 楼层增删改 ---------------- */

  const handleCreateFloor = () => {
    setEditingItem(null);
    floorForm.resetFields();
    floorForm.setFieldsValue({ is_active: true });
    if (selectedBuilding) {
      floorForm.setFieldsValue({ building_id: selectedBuilding.id });
    }
    setFloorModalVisible(true);
  };

  const handleEditFloor = (record: Floor) => {
    setEditingItem(record);
    floorForm.setFieldsValue(record);
    setFloorModalVisible(true);
  };

  const handleDeleteFloor = async (id: number) => {
    try {
      await campusApi.deleteFloor(id);
      message.success('删除成功');
      if (selectedFloor?.id === id) {
        setSelectedFloor(null);
      }
      if (selectedBuilding) {
        loadFloors(selectedBuilding.id);
      }
    } catch {
      message.error('删除失败');
    }
  };

  const handleFloorSubmit = async () => {
    try {
      const values = await floorForm.validateFields();
      // [新增 2026-09-17] 提交前统一规范化楼层号（兼容旧写法：3 → F3、-1 → B1、f03 → F3），
      // 避免用户未触发失焦直接提交时写入非规范值
      if (values.floor_number) {
        const normalized = normalizeFloorNumber(values.floor_number);
        if (normalized) values.floor_number = normalized;
      }
      if (editingItem) {
        await campusApi.updateFloor(editingItem.id, values);
        message.success('更新成功');
      } else {
        await campusApi.createFloor(values);
        message.success('创建成功');
      }
      setFloorModalVisible(false);
      if (selectedBuilding) {
        loadFloors(selectedBuilding.id);
      }
    } catch {
      message.error('操作失败');
    }
  };

  /* ---------------- 区域增删改 ---------------- */

  const handleCreateArea = () => {
    setEditingItem(null);
    areaForm.resetFields();
    areaForm.setFieldsValue({ is_active: true });
    if (selectedFloor) {
      areaForm.setFieldsValue({ floor_id: selectedFloor.id });
    }
    setAreaModalVisible(true);
  };

  const handleEditArea = (record: Area) => {
    setEditingItem(record);
    areaForm.setFieldsValue(record);
    setAreaModalVisible(true);
  };

  const handleDeleteArea = async (id: number) => {
    try {
      await campusApi.deleteArea(id);
      message.success('删除成功');
      if (selectedFloor) {
        loadAreas(selectedFloor.id);
      }
    } catch {
      message.error('删除失败');
    }
  };

  const handleAreaSubmit = async () => {
    try {
      const values = await areaForm.validateFields();
      if (editingItem) {
        await campusApi.updateArea(editingItem.id, values);
        message.success('更新成功');
      } else {
        await campusApi.createArea(values);
        message.success('创建成功');
      }
      setAreaModalVisible(false);
      if (selectedFloor) {
        loadAreas(selectedFloor.id);
      }
    } catch {
      message.error('操作失败');
    }
  };

  /* ---------------- 渲染 ---------------- */

  return (
    <PageContainer>
      <PageHeader
        title="院区管理"
        description="院区 → 楼栋 → 楼层 → 区域，逐级选择查看与维护"
        extra={
          <Button icon={<ReloadOutlined />} onClick={handleRefreshAll} loading={loadingCampus}>
            刷新
          </Button>
        }
      />

      {/* 四栏级联：align="stretch" 保证四栏等宽等高（齐平） */}
      <Row gutter={[16, 16]} align="stretch">
        {/* ① 院区 */}
        <Col xs={24} md={12} xl={6}>
          <CascadeColumn
            icon={<HomeOutlined />}
            title="院区"
            shown={filteredCampuses.length}
            total={campuses.length}
            parentHint="全部院区"
            addLabel="新增院区"
            onAdd={handleCreateCampus}
            keyword={kwCampus}
            onKeywordChange={setKwCampus}
            searchPlaceholder="搜索院区名称 / 代号"
            emptyWhenNoParent="暂无院区，点击右上角 + 新增"
            emptyWhenNoData="没有匹配的院区"
            hasItems={filteredCampuses.length > 0}
          >
            {filteredCampuses.map((c) => (
              <CascadeItem
                key={c.id}
                title={c.name}
                // [调整 2026-09-17] 按需求精简：院区项不再展示地址与楼栋数
                meta={c.code ? `代号 ${c.code}` : '未设置代号'}
                inactive={!c.is_active}
                selected={selectedCampus?.id === c.id}
                onSelect={() => handleSelectCampus(c)}
                onEdit={() => handleEditCampus(c)}
                onDelete={() => handleDeleteCampus(c.id)}
                deleteTitle="确定要删除此院区吗？"
              />
            ))}
          </CascadeColumn>
        </Col>

        {/* ② 楼栋 */}
        <Col xs={24} md={12} xl={6}>
          <CascadeColumn
            icon={<ApartmentOutlined />}
            title="楼栋"
            shown={filteredBuildings.length}
            total={buildings.length}
            parentName={selectedCampus?.name}
            parentHint="请先选择院区"
            addLabel="新增楼栋"
            onAdd={handleCreateBuilding}
            addDisabled={!selectedCampus}
            keyword={kwBuilding}
            onKeywordChange={setKwBuilding}
            searchPlaceholder="搜索楼栋名称 / 编号"
            emptyWhenNoParent="请先在上方选择一个院区"
            emptyWhenNoData="该院区暂无楼栋，点击右上角 + 新增"
            hasItems={filteredBuildings.length > 0}
          >
            {filteredBuildings.map((b) => (
              <CascadeItem
                key={b.id}
                title={b.name}
                meta={`编号 ${b.building_number} · ${b.floor_count} 个楼层`}
                inactive={!b.is_active}
                selected={selectedBuilding?.id === b.id}
                onSelect={() => handleSelectBuilding(b)}
                onEdit={() => handleEditBuilding(b)}
                onDelete={() => handleDeleteBuilding(b.id)}
                deleteTitle="确定要删除此楼栋吗？"
              />
            ))}
          </CascadeColumn>
        </Col>

        {/* ③ 楼层 */}
        <Col xs={24} md={12} xl={6}>
          <CascadeColumn
            icon={<AppstoreOutlined />}
            title="楼层"
            shown={filteredFloors.length}
            total={floors.length}
            parentName={selectedBuilding?.name}
            parentHint="请先选择楼栋"
            addLabel="新增楼层"
            onAdd={handleCreateFloor}
            addDisabled={!selectedBuilding}
            keyword={kwFloor}
            onKeywordChange={setKwFloor}
            searchPlaceholder="搜索楼层号 / 名称"
            emptyWhenNoParent="请先在上方选择一个楼栋"
            emptyWhenNoData="该楼栋暂无楼层，点击右上角 + 新增"
            hasItems={filteredFloors.length > 0}
          >
            {filteredFloors.map((f) => (
              <CascadeItem
                key={f.id}
                // [调整 2026-09-17] 标题优先楼层名称，副信息展示楼层号（F3 / B1）
                title={f.floor_name || f.floor_number}
                meta={f.floor_name
                  ? `${f.floor_number} · ${f.area_count} 个区域`
                  : `${f.area_count} 个区域`}
                inactive={!f.is_active}
                selected={selectedFloor?.id === f.id}
                onSelect={() => handleSelectFloor(f)}
                onEdit={() => handleEditFloor(f)}
                onDelete={() => handleDeleteFloor(f.id)}
                deleteTitle="确定要删除此楼层吗？"
              />
            ))}
          </CascadeColumn>
        </Col>

        {/* ④ 区域 */}
        <Col xs={24} md={12} xl={6}>
          <CascadeColumn
            icon={<BorderOutlined />}
            title="区域"
            shown={filteredAreas.length}
            total={areas.length}
            parentName={selectedFloor ? floorLabel(selectedFloor) : undefined}
            parentHint="请先选择楼层"
            addLabel="新增区域"
            onAdd={handleCreateArea}
            addDisabled={!selectedFloor}
            keyword={kwArea}
            onKeywordChange={setKwArea}
            searchPlaceholder="搜索区域名称 / 类型"
            emptyWhenNoParent="请先在上方选择一个楼层"
            emptyWhenNoData="该楼层暂无区域，点击右上角 + 新增"
            hasItems={filteredAreas.length > 0}
          >
            {filteredAreas.map((a) => (
              <CascadeItem
                key={a.id}
                title={a.name}
                meta={AREA_TYPE_TEXT[a.area_type] || a.area_type}
                inactive={!a.is_active}
                onSelect={() => {}}
                onEdit={() => handleEditArea(a)}
                onDelete={() => handleDeleteArea(a.id)}
                deleteTitle="确定要删除此区域吗？"
              />
            ))}
          </CascadeColumn>
        </Col>
      </Row>

      {/* ---------------- 院区编辑 ---------------- */}
      <Modal
        title={editingItem ? '编辑院区' : '新增院区'}
        open={campusModalVisible}
        onOk={handleCampusSubmit}
        onCancel={() => setCampusModalVisible(false)}
        width={600}
      >
        <Form form={campusForm} layout="vertical">
          <Form.Item
            name="name"
            label="院区名称"
            rules={[{ required: true, message: '请输入院区名称' }]}
          >
            <Input placeholder="请输入院区名称" />
          </Form.Item>
          <Form.Item name="code" label="院区代号">
            <Input placeholder="请输入院区代号（选填，如 HQ / EAST）" maxLength={50} />
          </Form.Item>
          <Form.Item name="address" label="地址">
            <Input placeholder="请输入地址" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="请输入描述" />
          </Form.Item>
          <Form.Item name="is_active" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ---------------- 楼栋编辑 ---------------- */}
      <Modal
        title={editingItem ? '编辑楼栋' : '新增楼栋'}
        open={buildingModalVisible}
        onOk={handleBuildingSubmit}
        onCancel={() => setBuildingModalVisible(false)}
        width={600}
      >
        <Form form={buildingForm} layout="vertical">
          <Form.Item name="campus_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="building_number"
            label="楼栋编号"
            rules={[{ required: true, message: '请输入楼栋编号' }]}
          >
            <Input placeholder="请输入楼栋编号" />
          </Form.Item>
          <Form.Item
            name="name"
            label="楼栋名称"
            rules={[{ required: true, message: '请输入楼栋名称' }]}
          >
            <Input placeholder="请输入楼栋名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="请输入描述" />
          </Form.Item>
          <Form.Item name="is_active" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ---------------- 楼层编辑 ---------------- */}
      <Modal
        title={editingItem ? '编辑楼层' : '新增楼层'}
        open={floorModalVisible}
        onOk={handleFloorSubmit}
        onCancel={() => setFloorModalVisible(false)}
        width={600}
      >
        <Form form={floorForm} layout="vertical">
          <Form.Item name="building_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="floor_number"
            label="楼层号"
            rules={[
              { required: true, message: '请输入楼层号' },
              {
                // [新增 2026-09-17] 支持字母编号：地上 F1/F2…、地下 B1/B2…；
                // 同时兼容旧习惯写法（3 → F3、-1 → B1），失焦与提交时自动规范化
                validator: (_, value) => {
                  if (!value) return Promise.resolve(); // 空值由 required 规则提示
                  return normalizeFloorNumber(value)
                    ? Promise.resolve()
                    : Promise.reject(new Error(FLOOR_NUMBER_HINT));
                },
              },
            ]}
            extra={FLOOR_NUMBER_HINT}
          >
            <Input
              placeholder="如 F3（三层）、B1（地下一层）"
              maxLength={5}
              allowClear
              onBlur={(e) => {
                // 失焦自动补全格式：f3 → F3、3 → F3、-1 → B1
                const normalized = normalizeFloorNumber(e.target.value);
                if (normalized) floorForm.setFieldsValue({ floor_number: normalized });
              }}
            />
          </Form.Item>
          <Form.Item name="floor_name" label="楼层名称">
            <Input placeholder="请输入楼层名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="请输入描述" />
          </Form.Item>
          <Form.Item name="is_active" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ---------------- 区域编辑 ---------------- */}
      <Modal
        title={editingItem ? '编辑区域' : '新增区域'}
        open={areaModalVisible}
        onOk={handleAreaSubmit}
        onCancel={() => setAreaModalVisible(false)}
        width={600}
      >
        <Form form={areaForm} layout="vertical">
          <Form.Item name="floor_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="name"
            label="区域名称"
            rules={[{ required: true, message: '请输入区域名称' }]}
          >
            <Input placeholder="请输入区域名称" />
          </Form.Item>
          <Form.Item
            name="area_type"
            label="区域类型"
            rules={[{ required: true, message: '请选择区域类型' }]}
          >
            <Select placeholder="请选择区域类型">
              <Option value="east">东区</Option>
              <Option value="west">西区</Option>
              <Option value="merged">合并区域</Option>
            </Select>
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="请输入描述" />
          </Form.Item>
          <Form.Item name="is_active" label="状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
};

export default CampusManagement;
