// [修复 2026-09-05] 平面设置页面：平面图资产完整 CRUD 管理（迁入标识设置菜单）
import React, { useState, useEffect } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Card, Table, Button, Space, Modal, Form, Input, Select, Upload,
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
// [调整 2026-09-17] 楼层展示统一收敛到 utils/floor（楼层号已为 F3/B1 字母编号）
import { floorLabel } from '../../utils/floor';

const { Title, Text } = Typography;

// [修复 2026-09-05] 平面类别枚举
const CATEGORIES = ['院区平面', '楼层平面'];

// [调整 2026-09-17] 原有的本地 floorLabel / floorCodeOf 已移除：
// 楼层号本身即字母编号（F3 = 三层、B1 = 地下一层），
// 展示统一走 utils/floor 的 floorLabel（F3-门诊层），楼层编码直接取 floor_number。

const PlanSettings: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
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
              // [调整 2026-09-17] 历史数据兜底匹配：floor_code 即楼层号（F3 / B1）
              const f = (record.floor_id && fr.items.find((x) => x.id === record.floor_id))
                || fr.items.find((x) => (x.floor_number || '') === (record.floor_code || ''));
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
        // [调整 2026-09-17] 楼层编码即楼层号本身（F3 / B1）
        floor_code: isFloorPlan && floor ? floor.floor_number : null,
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

  /**
   * [调整 2026-09-17] 列宽收敛，消除横向滚动。
   *
   * 原问题：Table 未设 tableLayout（默认 auto 布局），而「名称 / 院区·楼栋 / 描述」
   * 三列都没有宽度 —— 名称或描述稍长就会把表格撑出容器，出现左右拖动。
   *
   * 处理：
   *   1) 每列都设固定宽度（描述列由 tableLayout="fixed" 自动获得剩余空间）；
   *   2) 名称 / 院区·楼栋 / 关联楼层 / 描述 加 ellipsis，超长以省略号收尾
   *      （注意：auto 布局下 ellipsis 不会真正截断，必须配合列宽与 fixed 布局）；
   *   3) Table 设 tableLayout="fixed"，严格遵守列宽，不再被内容撑宽。
   *
   * 固定列合计 710px，描述列在 1000px 容器下仍可分到约 290px。
   */
  const columns = [
    {
      title: '缩略图',
      dataIndex: 'image_url',
      key: 'image_url',
      // [调整 2026-09-19] 72 → 84：该列是全表最窄列，72px 减去左右内边距后
      // 仅剩 48px，正好卡在表头「缩略图」三个字（约 42px）的临界点上，
      // 稍有字号/字重变化就会溢出到相邻列。加宽到 84 后表头与缩略图都从容。
      width: 84,
      render: (url?: string) => (
        <SafeImage
          src={url || null}
          alt="平面图"
          style={{ width: 48, height: 36, objectFit: 'cover', borderRadius: 6 }}
        />
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 160,
      ellipsis: true,
      render: (t: string) => <Text strong>{t}</Text>,
    },
    {
      title: '类别',
      dataIndex: 'category',
      key: 'category',
      width: 88,
      render: (c: string) => <Tag color={c === '院区平面' ? 'blue' : 'cyan'}>{c}</Tag>,
    },
    {
      title: '院区/楼栋',
      key: 'location',
      width: 150,
      ellipsis: true,
      render: (_: any, r: FloorPlan) => (
        <span>{r.campus || '-'}{r.building ? ` / ${r.building}` : ''}</span>
      ),
    },
    {
      title: '关联楼层',
      key: 'floor',
      width: 120,
      ellipsis: true,
      render: (_: any, r: FloorPlan) => (
        <span>
          {r.floor || r.floor_code || '-'}
          {r.floor && r.floor_code ? (
            <Text type="secondary" style={{ marginLeft: 6 }}>{r.floor_code}</Text>
          ) : null}
        </span>
      ),
    },
    {
      // [调整 2026-09-17] 描述为自由文本：不设宽度，由 tableLayout="fixed" 分得剩余空间，
      // 超出以省略号收尾（原先无宽度时会被长文本撑宽整张表）
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (t?: string) => t || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
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
          // [新增 2026-09-17] 固定表格布局：严格遵守列宽，长文本由 ellipsis 截断，
          // 不再把表格撑出容器（这是原先需要左右拖动的根因）
          tableLayout="fixed"
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
                options={floors.map((f) => ({ value: f.id, label: floorLabel(f) }))}
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
                  border: '1px dashed var(--line-soft)', borderRadius: 8, padding: 16,
                  textAlign: 'center', cursor: 'pointer', color: 'var(--text-2)',
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
