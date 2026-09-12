// [修复 2026-09-05] 平面设置页面：平面图资产完整 CRUD 管理（迁入标识设置菜单）
import React, { useState, useEffect } from 'react';
import {
  Card, Table, Button, Space, Modal, Form, Input, Select, Upload, message,
  Popconfirm, Tag, Breadcrumb, Typography, Row, Col,
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined,
  HomeOutlined, ApartmentOutlined, UploadOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import {
  getFloorPlanList, createFloorPlan, updateFloorPlan, deleteFloorPlan, uploadFloorPlanImage,
} from '../../api/signage';
import type { FloorPlan } from '../../api/signage';
import { campusApi } from '../../api/campus';
import type { Campus, Building, Floor } from '../../types/campus';
import SafeImage from '../../components/SafeImage';

const { Title, Text } = Typography;

// [修复 2026-09-05] 平面类别枚举
const CATEGORIES = ['院区平面', '楼层平面'];

// [修复 2026-09-05] 楼层显示名：优先使用院区管理中维护的楼层名称，否则由楼层号生成（负数表示地下层）
const floorLabel = (f: Floor) =>
  f.floor_name || (f.floor_number < 0 ? `地下${Math.abs(f.floor_number)}层` : `${f.floor_number}层`);

// [修复 2026-09-05] 楼层编号编码：地上记为 F3，地下记为 -1
const floorCodeOf = (f: Floor) => (f.floor_number < 0 ? `${f.floor_number}` : `F${f.floor_number}`);

const PlanSettings: React.FC = () => {
  const [plans, setPlans] = useState<FloorPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  const [modalVisible, setModalVisible] = useState(false);
  const [editing, setEditing] = useState<FloorPlan | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  // [修复 2026-09-05] 院区/楼栋级联
  const [campuses, setCampuses] = useState<Campus[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  // [修复 2026-09-05] 楼层列表：来源于院区管理，随所选楼栋级联加载
  const [floors, setFloors] = useState<Floor[]>([]);
  const [selCampusId, setSelCampusId] = useState<number | undefined>();
  const [selBuildingId, setSelBuildingId] = useState<number | undefined>();
  const [category, setCategory] = useState<string>('楼层平面');
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | undefined>();
  const [uploading, setUploading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const items = await getFloorPlanList({ category: categoryFilter });
      const kw = search.trim().toLowerCase();
      setPlans(
        kw
          ? items.filter((p) => p.name.toLowerCase().includes(kw) || (p.campus || '').toLowerCase().includes(kw))
          : items,
      );
    } catch {
      message.error('获取平面图列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [search, categoryFilter]);

  useEffect(() => {
    campusApi.getAllCampuses().then(setCampuses).catch(() => message.error('获取院区列表失败'));
  }, []);

  const openAdd = () => {
    setEditing(null);
    setCategory('楼层平面');
    setSelCampusId(undefined);
    setSelBuildingId(undefined);
    setBuildings([]);
    setFloors([]);
    setImageFile(null);
    setImagePreview(undefined);
    form.resetFields();
    form.setFieldsValue({ category: '楼层平面' });
    setModalVisible(true);
  };

  const openEdit = (record: FloorPlan) => {
    setEditing(record);
    setCategory(record.category);
    setImageFile(null);
    setImagePreview(record.image_url);
    const campus = campuses.find((c) => c.name === record.campus);
    setSelCampusId(campus?.id);
    if (campus) {
      campusApi.getBuildings(campus.id)
        .then(async (r) => {
          setBuildings(r.items);
          const b = r.items.find((x) => x.name === record.building);
          setSelBuildingId(b?.id);
          form.setFieldsValue({ buildingId: b?.id });
          // [修复 2026-09-05] 按所选楼栋加载院区管理中的楼层，并回填该平面图已关联的楼层
          if (b) {
            try {
              const fr = await campusApi.getFloors(b.id);
              setFloors(fr.items);
              // 优先按 floor_id 精确匹配；历史数据仅有楼层编号时按编码兜底匹配
              const f = (record.floor_id && fr.items.find((x) => x.id === record.floor_id))
                || fr.items.find((x) => floorCodeOf(x) === record.floor_code);
              form.setFieldsValue({ floorId: f?.id });
            } catch {
              message.error('获取楼层失败');
            }
          } else {
            setFloors([]);
            form.setFieldsValue({ floorId: undefined });
          }
        })
        .catch(() => message.error('获取楼栋失败'));
    } else {
      setBuildings([]);
      setFloors([]);
    }
    form.setFieldsValue({
      name: record.name,
      category: record.category,
      campusId: campus?.id,
      description: record.description,
    });
    setModalVisible(true);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteFloorPlan(id);
      message.success('删除成功');
      load();
    } catch {
      message.error('删除失败');
    }
  };

  const handleOk = async () => {
    try {
      const v = await form.validateFields();
      const campus = campuses.find((c) => c.id === selCampusId);
      const building = buildings.find((b) => b.id === selBuildingId);
      // [修复 2026-09-05] 楼层取自院区管理中已维护的楼层记录，不再由用户手工输入
      const floor = floors.find((f) => f.id === v.floorId);
      const isFloorPlan = v.category === '楼层平面';
      const payload: Partial<FloorPlan> = {
        name: v.name,
        category: v.category,
        // [修复 2026-09-05] 院区平面只存院区名；楼层平面额外关联楼栋与楼层
        campus: campus?.name,
        // 显式置 null，确保从楼层平面改回院区平面时清空楼栋/楼层关联
        building: isFloorPlan ? building?.name ?? null : null,
        floor_id: isFloorPlan ? floor?.id ?? null : null,
        floor: isFloorPlan && floor ? floorLabel(floor) : null,
        floor_code: isFloorPlan && floor ? floorCodeOf(floor) : null,
        description: v.description,
      };
      setSaving(true);
      if (editing) {
        await updateFloorPlan(editing.id, payload);
        if (imageFile) {
          setUploading(true);
          await uploadFloorPlanImage(editing.id, imageFile);
          setUploading(false);
        }
        message.success('保存成功');
      } else {
        const created = await createFloorPlan(payload);
        if (imageFile) {
          setUploading(true);
          await uploadFloorPlanImage(created.id, imageFile);
          setUploading(false);
        }
        message.success('创建成功');
      }
      setModalVisible(false);
      load();
    } catch (error) {
      if (!(error && typeof error === 'object' && 'errorFields' in error)) {
        message.error('操作失败');
      }
    } finally {
      setSaving(false);
    }
  };

  const beforeUpload = (file: File) => {
    const ok = file.type === 'image/svg+xml' || file.type.startsWith('image/');
    if (!ok) { message.error('仅支持 SVG / JPG / PNG 图片！'); return false; }
    const isLt20M = file.size / 1024 / 1024 < 20;
    if (!isLt20M) { message.error('图片大小不能超过 20MB！'); return false; }
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
    return false;
  };

  const columns = [
    {
      title: '缩略图',
      dataIndex: 'image_url',
      key: 'image_url',
      width: 80,
      render: (url?: string) => (
        <SafeImage
          src={url || null}
          alt="平面图"
          style={{ width: 56, height: 40, objectFit: 'cover', borderRadius: 6 }}
        />
      ),
    },
    { title: '名称', dataIndex: 'name', key: 'name', render: (t: string) => <Text strong>{t}</Text> },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      render: (c: string) => <Tag color={c === '院区平面' ? 'blue' : 'cyan'}>{c}</Tag>,
    },
    {
      title: '院区/楼栋',
      key: 'location',
      render: (_: any, r: FloorPlan) => (
        <span>{r.campus || '-'}{r.building ? ` / ${r.building}` : ''}</span>
      ),
    },
    {
      title: '关联楼层',
      key: 'floor',
      width: 150,
      render: (_: any, r: FloorPlan) => (
        <span>
          {r.floor || r.floor_code || '-'}
          {r.floor && r.floor_code ? (
            <Text type="secondary" style={{ marginLeft: 6 }}>{r.floor_code}</Text>
          ) : null}
        </span>
      ),
    },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true, render: (t?: string) => t || '-' },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_: any, r: FloorPlan) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除该平面图吗？" onConfirm={() => handleDelete(r.id)} okText="确定" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
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
          { title: <Link to="/dashboard"><HomeOutlined /> 首页</Link> },
          { title: <Link to="/signage-settings">标识设置</Link> },
          { title: '平面设置' },
        ]}
      />

      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <ApartmentOutlined style={{ marginRight: 8 }} />
            平面设置
          </Title>
          <Text type="secondary">管理平面图资产，支持 SVG / JPG / PNG 上传与标识点位标记</Text>
        </Col>
        <Col>
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新建平面图</Button>
        </Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="plan-search"
            placeholder="搜索名称或院区"
            prefix={<SearchOutlined />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 260 }}
            allowClear
          />
          <Select
            placeholder="平面类别"
            style={{ width: 160 }}
            value={categoryFilter}
            onChange={setCategoryFilter}
            allowClear
            options={CATEGORIES.map((c) => ({ value: c, label: c }))}
          />
        </Space>
        <Table
          columns={columns}
          dataSource={plans}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>

      <Modal
        title={editing ? '编辑平面图' : '新建平面图'}
        open={modalVisible}
        onOk={handleOk}
        onCancel={() => setModalVisible(false)}
        confirmLoading={saving || uploading}
        width={600}
        okText="确定"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onValuesChange={(changed) => {
          if ('category' in changed) setCategory(changed.category as string);
          if ('campusId' in changed) {
            const id = changed.campusId as number | undefined;
            setSelCampusId(id);
            setSelBuildingId(undefined);
            setFloors([]);
            form.setFieldsValue({ buildingId: undefined, floorId: undefined });
            if (id) {
              campusApi.getBuildings(id).then((r) => setBuildings(r.items)).catch(() => message.error('获取楼栋失败'));
            } else {
              setBuildings([]);
            }
          }
          // [修复 2026-09-05] 切换楼栋时级联加载该楼栋下的楼层（数据来源于院区管理）
          if ('buildingId' in changed) {
            const bid = changed.buildingId as number | undefined;
            setSelBuildingId(bid);
            setFloors([]);
            form.setFieldsValue({ floorId: undefined });
            if (bid) {
              campusApi.getFloors(bid).then((r) => setFloors(r.items)).catch(() => message.error('获取楼层失败'));
            }
          }
        }}>
          <Form.Item name="name" label="平面图名称" rules={[{ required: true, message: '请输入平面图名称' }]}>
            <Input placeholder="例如：门诊楼1层平面图" />
          </Form.Item>
          <Form.Item name="category" label="平面类别" rules={[{ required: true }]} initialValue="楼层平面">
            <Select
              options={CATEGORIES.map((c) => ({ value: c, label: c }))}
            />
          </Form.Item>
          <Form.Item name="campusId" label="所属院区" rules={[{ required: true, message: '请选择院区' }]}>
            <Select
              placeholder="请选择院区"
              showSearch
              optionFilterProp="label"
              options={campuses.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
          {category === '楼层平面' && (
            <Form.Item name="buildingId" label="关联楼栋" rules={[{ required: true, message: '请选择楼栋' }]}>
              <Select
                placeholder="请选择楼栋"
                disabled={!selCampusId}
                showSearch
                optionFilterProp="label"
                options={buildings.map((b) => ({ value: b.id, label: `${b.name} (${b.building_number})` }))}
              />
            </Form.Item>
          )}
          {category === '楼层平面' && (
            <Form.Item
              name="floorId"
              label="关联楼层"
              rules={[{ required: true, message: '请选择关联楼层' }]}
              extra="楼层数据来源于「院区管理」，请先选择院区与楼栋"
            >
              <Select
                placeholder="请选择楼层"
                disabled={!selBuildingId}
                showSearch
                optionFilterProp="label"
                options={floors.map((f) => ({ value: f.id, label: `${floorLabel(f)}（${floorCodeOf(f)}）` }))}
              />
            </Form.Item>
          )}
          <Form.Item name="description" label="平面图描述">
            <Input.TextArea placeholder="请输入平面图描述（选填）" rows={3} />
          </Form.Item>
          <Form.Item label="平面图图片">
            <Upload
              accept=".svg,image/svg+xml,image/jpeg,image/png"
              beforeUpload={beforeUpload}
              showUploadList={false}
              customRequest={() => {}}
            >
              <div
                style={{
                  border: '1px dashed #d9d9d9', borderRadius: 8, padding: 16,
                  textAlign: 'center', cursor: 'pointer', color: '#5C6B7A',
                }}
              >
                {imagePreview ? (
                  <img src={imagePreview} alt="预览" style={{ maxHeight: 160, maxWidth: '100%', borderRadius: 6 }} />
                ) : (
                  <><UploadOutlined style={{ fontSize: 20 }} /><div style={{ marginTop: 8 }}>点击选择 SVG / JPG / PNG 图片</div></>
                )}
              </div>
            </Upload>
            {imagePreview && (
              <Button type="link" size="small" onClick={() => { setImageFile(null); setImagePreview(undefined); }}>
                移除图片
              </Button>
            )}
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default PlanSettings;
