import React, { useState, useEffect } from 'react';
import {
  Card, Table, Button, Space, Modal, Form, Input, Select, Tree, message,
  Popconfirm, Tag, Tooltip, Breadcrumb, Row, Col, Tabs, Switch, InputNumber
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined,
  // [修复 2026-09-05] 移除不存在的 BuildingOutlined 导入（应为 BuildOutlined 的笔误，且未被使用），消除 TS2724 构建报错
  HomeOutlined, ApartmentOutlined, TeamOutlined,
  ReloadOutlined, ExpandOutlined, CompressOutlined
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { campusApi } from '../../api/campus';
import type { 
  Campus, Building, Floor, Area,
  CampusCreate, BuildingCreate, FloorCreate, AreaCreate,
  CampusTreeNode
} from '../../types/campus';

const { TabPane } = Tabs;
const { Option } = Select;

// [修复 2026-09-03] 院区-楼栋-楼层-区域管理页面
const CampusManagement: React.FC = () => {
  // 状态管理
  const [campuses, setCampuses] = useState<Campus[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [floors, setFloors] = useState<Floor[]>([]);
  const [areas, setAreas] = useState<Area[]>([]);
  
  const [selectedCampus, setSelectedCampus] = useState<Campus | null>(null);
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(null);
  const [selectedFloor, setSelectedFloor] = useState<Floor | null>(null);
  
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [activeTab, setActiveTab] = useState('campuses');
  
  // 模态框状态
  const [campusModalVisible, setCampusModalVisible] = useState(false);
  const [buildingModalVisible, setBuildingModalVisible] = useState(false);
  const [floorModalVisible, setFloorModalVisible] = useState(false);
  const [areaModalVisible, setAreaModalVisible] = useState(false);
  
  const [editingItem, setEditingItem] = useState<any>(null);
  const [form] = Form.useForm();
  const [campusForm] = Form.useForm();
  const [buildingForm] = Form.useForm();
  const [floorForm] = Form.useForm();
  const [areaForm] = Form.useForm();

  // 加载数据
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

  // 数据加载函数
  const loadCampuses = async () => {
    try {
      setLoading(true);
      const response = await campusApi.getCampuses(1, 100, searchText);
      setCampuses(response.items);
    } catch (error) {
      message.error('加载院区列表失败');
    } finally {
      setLoading(false);
    }
  };

  const loadBuildings = async (campusId: number) => {
    try {
      setLoading(true);
      const response = await campusApi.getBuildings(campusId);
      setBuildings(response.items);
    } catch (error) {
      message.error('加载楼栋列表失败');
    } finally {
      setLoading(false);
    }
  };

  const loadFloors = async (buildingId: number) => {
    try {
      setLoading(true);
      const response = await campusApi.getFloors(buildingId);
      setFloors(response.items);
    } catch (error) {
      message.error('加载楼层列表失败');
    } finally {
      setLoading(false);
    }
  };

  const loadAreas = async (floorId: number) => {
    try {
      setLoading(true);
      const response = await campusApi.getAreas(floorId);
      setAreas(response.items);
    } catch (error) {
      message.error('加载区域列表失败');
    } finally {
      setLoading(false);
    }
  };

  // 搜索
  const handleSearch = () => {
    loadCampuses();
  };

  // 院区操作
  const handleCreateCampus = () => {
    setEditingItem(null);
    campusForm.resetFields();
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
      loadCampuses();
    } catch (error) {
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
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 楼栋操作
  const handleCreateBuilding = () => {
    setEditingItem(null);
    buildingForm.resetFields();
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
      if (selectedCampus) {
        loadBuildings(selectedCampus.id);
      }
    } catch (error) {
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
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 楼层操作
  const handleCreateFloor = () => {
    setEditingItem(null);
    floorForm.resetFields();
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
      if (selectedBuilding) {
        loadFloors(selectedBuilding.id);
      }
    } catch (error) {
      message.error('删除失败');
    }
  };

  const handleFloorSubmit = async () => {
    try {
      const values = await floorForm.validateFields();
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
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 区域操作
  const handleCreateArea = () => {
    setEditingItem(null);
    areaForm.resetFields();
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
    } catch (error) {
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
    } catch (error) {
      message.error('操作失败');
    }
  };

  // 选择院区
  const handleSelectCampus = (record: Campus) => {
    setSelectedCampus(record);
    setSelectedBuilding(null);
    setSelectedFloor(null);
  };

  // 选择楼栋
  const handleSelectBuilding = (record: Building) => {
    setSelectedBuilding(record);
    setSelectedFloor(null);
  };

  // 选择楼层
  const handleSelectFloor = (record: Floor) => {
    setSelectedFloor(record);
  };

  // 院区表格列定义
  const campusColumns = [
    {
      title: '院区名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Campus) => (
        <Button type="link" onClick={() => handleSelectCampus(record)}>
          {text}
        </Button>
      ),
    },
    {
      title: '院区代号',
      dataIndex: 'code',
      key: 'code',
      render: (code?: string) => code || <span style={{ color: '#bfbfbf' }}>—</span>,
    },
    {
      title: '地址',
      dataIndex: 'address',
      key: 'address',
    },
    {
      title: '楼栋数',
      dataIndex: 'building_count',
      key: 'building_count',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (is_active: boolean) => (
        <Tag color={is_active ? 'green' : 'red'}>
          {is_active ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Campus) => (
        <Space>
          <Tooltip title="编辑">
            <Button type="link" icon={<EditOutlined />} onClick={() => handleEditCampus(record)} />
          </Tooltip>
          <Popconfirm
            title="确定要删除此院区吗？"
            onConfirm={() => handleDeleteCampus(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="link" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 楼栋表格列定义
  const buildingColumns = [
    {
      title: '楼栋编号',
      dataIndex: 'building_number',
      key: 'building_number',
    },
    {
      title: '楼栋名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Building) => (
        <Button type="link" onClick={() => handleSelectBuilding(record)}>
          {text}
        </Button>
      ),
    },
    {
      title: '楼层数',
      dataIndex: 'floor_count',
      key: 'floor_count',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (is_active: boolean) => (
        <Tag color={is_active ? 'green' : 'red'}>
          {is_active ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Building) => (
        <Space>
          <Tooltip title="编辑">
            <Button type="link" icon={<EditOutlined />} onClick={() => handleEditBuilding(record)} />
          </Tooltip>
          <Popconfirm
            title="确定要删除此楼栋吗？"
            onConfirm={() => handleDeleteBuilding(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="link" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 楼层表格列定义
  const floorColumns = [
    {
      title: '楼层号',
      dataIndex: 'floor_number',
      key: 'floor_number',
    },
    {
      title: '楼层名称',
      dataIndex: 'floor_name',
      key: 'floor_name',
      render: (text: string, record: Floor) => (
        <Button type="link" onClick={() => handleSelectFloor(record)}>
          {text || `第${record.floor_number}层`}
        </Button>
      ),
    },
    {
      title: '区域数',
      dataIndex: 'area_count',
      key: 'area_count',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (is_active: boolean) => (
        <Tag color={is_active ? 'green' : 'red'}>
          {is_active ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Floor) => (
        <Space>
          <Tooltip title="编辑">
            <Button type="link" icon={<EditOutlined />} onClick={() => handleEditFloor(record)} />
          </Tooltip>
          <Popconfirm
            title="确定要删除此楼层吗？"
            onConfirm={() => handleDeleteFloor(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="link" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 区域表格列定义
  const areaColumns = [
    {
      title: '区域名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '区域类型',
      dataIndex: 'area_type',
      key: 'area_type',
      render: (area_type: string) => {
        const typeMap: Record<string, { color: string; text: string }> = {
          east: { color: 'blue', text: '东区' },
          west: { color: 'green', text: '西区' },
          merged: { color: 'orange', text: '合并区域' },
        };
        const typeInfo = typeMap[area_type] || { color: 'gray', text: area_type };
        return <Tag color={typeInfo.color}>{typeInfo.text}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (is_active: boolean) => (
        <Tag color={is_active ? 'green' : 'red'}>
          {is_active ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Area) => (
        <Space>
          <Tooltip title="编辑">
            <Button type="link" icon={<EditOutlined />} onClick={() => handleEditArea(record)} />
          </Tooltip>
          <Popconfirm
            title="确定要删除此区域吗？"
            onConfirm={() => handleDeleteArea(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Tooltip title="删除">
              <Button type="link" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* [修复 2026-09-05] 迁移到 antd v5 的 items 写法，消除 Breadcrumb.Item 弃用告警 */}
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link to="/dashboard">首页</Link> },
          { title: '院区管理' },
        ]}
      />

      <Card title="院区-楼栋-楼层-区域管理" style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          {/* 左侧：院区列表 */}
          <Col span={8}>
            <Card 
              title="院区列表" 
              size="small"
              extra={
                <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateCampus}>
                  新增院区
                </Button>
              }
            >
              <Space style={{ marginBottom: 12, width: '100%' }}>
                <Input
                  // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
                  id="campus-search"
                  placeholder="搜索院区"
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  onPressEnter={handleSearch}
                  style={{ width: 200 }}
                />
                <Button icon={<SearchOutlined />} onClick={handleSearch} />
                <Button icon={<ReloadOutlined />} onClick={loadCampuses} />
              </Space>
              <Table
                columns={campusColumns}
                dataSource={campuses}
                rowKey="id"
                loading={loading}
                size="small"
                pagination={false}
                rowClassName={(record) => selectedCampus?.id === record.id ? 'ant-table-row-selected' : ''}
              />
            </Card>
          </Col>

          {/* 中间：楼栋列表 */}
          <Col span={8}>
            <Card 
              title={`楼栋列表 - ${selectedCampus?.name || '请选择院区'}`} 
              size="small"
              extra={
                <Button 
                  type="primary" 
                  icon={<PlusOutlined />} 
                  onClick={handleCreateBuilding}
                  disabled={!selectedCampus}
                >
                  新增楼栋
                </Button>
              }
            >
              <Table
                columns={buildingColumns}
                dataSource={buildings}
                rowKey="id"
                loading={loading}
                size="small"
                pagination={false}
                rowClassName={(record) => selectedBuilding?.id === record.id ? 'ant-table-row-selected' : ''}
              />
            </Card>
          </Col>

          {/* 右侧：楼层和区域列表 */}
          <Col span={8}>
            <Card 
              title={`楼层列表 - ${selectedBuilding?.name || '请选择楼栋'}`} 
              size="small"
              extra={
                <Button 
                  type="primary" 
                  icon={<PlusOutlined />} 
                  onClick={handleCreateFloor}
                  disabled={!selectedBuilding}
                >
                  新增楼层
                </Button>
              }
              style={{ marginBottom: 16 }}
            >
              <Table
                columns={floorColumns}
                dataSource={floors}
                rowKey="id"
                loading={loading}
                size="small"
                pagination={false}
                rowClassName={(record) => selectedFloor?.id === record.id ? 'ant-table-row-selected' : ''}
              />
            </Card>

            <Card 
              title={`区域列表 - ${selectedFloor?.floor_name || `第${selectedFloor?.floor_number || ''}层`}`} 
              size="small"
              extra={
                <Button 
                  type="primary" 
                  icon={<PlusOutlined />} 
                  onClick={handleCreateArea}
                  disabled={!selectedFloor}
                >
                  新增区域
                </Button>
              }
            >
              <Table
                columns={areaColumns}
                dataSource={areas}
                rowKey="id"
                loading={loading}
                size="small"
                pagination={false}
              />
            </Card>
          </Col>
        </Row>
      </Card>

      {/* 院区编辑模态框 */}
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

      {/* 楼栋编辑模态框 */}
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

      {/* 楼层编辑模态框 */}
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
            rules={[{ required: true, message: '请输入楼层号' }]}
          >
            <InputNumber min={-10} max={100} placeholder="请输入楼层号" style={{ width: '100%' }} />
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

      {/* 区域编辑模态框 */}
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
    </div>
  );
};

export default CampusManagement;