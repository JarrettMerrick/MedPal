// [修复 2026-09-04] 标识分类设置页面：维护标识分类选项
import React, { useState, useEffect } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Card, Table, Button, Space, Modal, Form, Input, Select, InputNumber,
  Popconfirm, Tag, Breadcrumb, Typography, Row, Col
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined,
  HomeOutlined, TagsOutlined
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { getSignageCategories, createSignageCategory, updateSignageCategory, deleteSignageCategory } from '../../api/signage-settings';
import type { SignageCategory } from '../../api/signage-settings';
// [修复 2026-09-05] 标记形状：与平面标记页共用同一套形状定义与渲染
import MarkerShapeIcon, { MARKER_SHAPES, MARKER_SHAPE_LABELS } from '../../components/MarkerShape';
// [统一时间口径] 时间展示一律走 utils/time（原 updated_at 列未加 render，直接把 UTC 原值显示出来）
import { formatDateTimeStandard } from '../../utils/time';

const { Title, Text } = Typography;

// [修复 2026-09-05] 24 色预设色板 + 自定义十六进制颜色
const CATEGORY_COLORS = [
  '#E03131', '#F76707', '#FD7E14', '#FCC419', '#FAB005', '#94D82D',
  '#82C91E', '#37B24D', '#0CA678', '#0E7F8A', '#1098AD', '#15AABF',
  '#1C7ED6', '#4263EB', '#5F3DC4', '#7048E8', '#9775FA', '#9C36B5',
  '#E64980', '#F783AC', '#C2255C', '#868E96', '#495057', '#3a321fff',
];

const isHexColor = (v?: string): boolean => !!v && /^#[0-9A-Fa-f]{6}$/.test(v);

// [修复 2026-09-05] 分类颜色选择：24 色色板点选 + 自定义十六进制输入。
// [修复 2026-09-05] 接收并透传 Form.Item 注入的 id：此前自定义控件丢弃了 id，
// 导致 label 的 for 指向不存在的元素（Incorrect use of <label for> 告警）
const ColorField: React.FC<{ value?: string; onChange?: (v?: string) => void; id?: string }> = ({ value, onChange, id }) => (
  <div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 6, marginBottom: 10 }}>
      {CATEGORY_COLORS.map((c) => (
        <button
          type="button"
          key={c}
          title={c}
          onClick={() => onChange?.(c)}
          style={{
            /* [改造 2026-09-19] 选中环与间隔环改引用变量（色板本身为业务色，保持不变） */
            width: 24, height: 24, borderRadius: '50%', background: c,
            border: value === c ? '3px solid var(--accent)' : '2px solid var(--neu-bg)',
            boxShadow: '0 0 0 1px var(--line-soft)', cursor: 'pointer', padding: 0,
          }}
        />
      ))}
    </div>
    <Input
      id={id}
      addonBefore={
        <span style={{
          display: 'inline-block', width: 16, height: 16, borderRadius: 4,
          background: isHexColor(value) ? value : 'var(--neu-bg)', border: '1px solid var(--line-soft)',
        }} />
      }
      placeholder="#RRGGBB"
      maxLength={7}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  </div>
);

// [修复 2026-09-04] 标识分类设置页面组件
const SignageCategorySettings: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  // 状态管理
  const [categories, setCategories] = useState<SignageCategory[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [modalVisible, setModalVisible] = useState(false);
  const [editingItem, setEditingItem] = useState<SignageCategory | null>(null);
  const [form] = Form.useForm();

  // [修复 2026-09-04] 从后端API加载分类数据
  const loadCategories = async () => {
    setLoading(true);
    try {
      const result = await getSignageCategories({ page: 1, page_size: 100, search: searchText || undefined });
      setCategories(result.items);
    } catch {
      message.error('获取分类列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCategories();
  }, []);

  // 搜索变化时重新加载
  useEffect(() => {
    loadCategories();
  }, [searchText]);

  // [修复 2026-09-04] 表格列定义
  const columns = [
    {
      title: '分类名称',
      dataIndex: 'name',
      key: 'name',
      // [调整 2026-09-19] 220 → 140：实测库中分类名称最长仅「温馨提示牌」5 字
      // （约 70px），220px 有一半以上是空白，属于典型的"列宽与实际内容脱节"。
      width: 140,
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: '分类编码',
      dataIndex: 'code',
      key: 'code',
      // [调整 2026-09-19] 130 → 110：实测编码最长 5 字符（「WXTSP」），
      // 列内是 Tag（自带内边距），110px 已足够并留有换行余量。
      width: 110,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      // [调整 2026-09-19] 去掉 ellipsis，改为**独占剩余空间 + 允许换行**：
      // 描述是自由文本（实测最长「温馨提示牌（测试分类）」11 字，但业务上会更长），
      // 原先用省略号截断会让用户看不到完整描述；改为换行后既不截断、也不会撑宽表格。
      // 不设 width → 由它吸收所有剩余空间，配合全局 .ant-table-wrapper table{width:100%}
      // 保证表格总宽恒等于容器，不会出现横向滚动。
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 140 } as React.CSSProperties,
      }),
    },
    {
      // [修复 2026-09-05] 标记样式列：形状 + 颜色组合预览，与平面图标记展示一致
      title: '标记样式',
      key: 'marker_style',
      width: 110,
      render: (_: any, r: SignageCategory) => (
        <Space size={6}>
          <MarkerShapeIcon shape={r.shape} color={isHexColor(r.color) ? r.color : '#CED4DA'} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {MARKER_SHAPE_LABELS[r.shape || 'circle'] || '圆形'}
          </Text>
        </Space>
      ),
    },
    {
      // [新增 2026-09-05] 巡检周期列：留空表示不参与巡检预警
      title: '巡检周期',
      dataIndex: 'inspection_cycle_days',
      key: 'inspection_cycle_days',
      width: 90,
      render: (v?: number) => (v ? `${v} 天` : <Text type="secondary">不参与</Text>),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      render: (isActive: boolean) => (
        <Tag color={isActive ? 'green' : 'default'}>
          {isActive ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      // [调整 2026-09-19] 160 → 110，并改为「日期 / 时间」两行展示：
      // 完整时间串 19 字符在 110px 内会被折成三行（2026- / 09-19 / 11:20:33），
      // 两行展示既省宽度又好读（与供应商设置页的处理保持一致）。
      width: 110,
      // [统一时间口径] 补 render：原实现直接输出后端 UTC 串，比北京时间少 8 小时
      render: (v: string) => {
        if (!v) return '-';
        const [date, time] = formatDateTimeStandard(v).split(' ');
        return (
          <div style={{ lineHeight: 1.35 }}>
            <div>{date}</div>
            {time && <div style={{ fontSize: 12, opacity: 0.72 }}>{time}</div>}
          </div>
        );
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: any, record: SignageCategory) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个分类吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // [修复 2026-09-04] 处理新增/编辑
  const handleAdd = () => {
    setEditingItem(null);
    form.resetFields();
    setModalVisible(true);
  };

  const handleEdit = (record: SignageCategory) => {
    setEditingItem(record);
    form.setFieldsValue(record);
    setModalVisible(true);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteSignageCategory(id);
      message.success('删除成功');
      loadCategories();
    } catch {
      message.error('删除失败');
    }
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingItem) {
        await updateSignageCategory(editingItem.id, values);
        message.success('编辑成功');
      } else {
        await createSignageCategory({ ...values, is_active: true } as any);
        message.success('新增成功');
      }
      setModalVisible(false);
      form.resetFields();
      loadCategories();
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) {
        // 表单验证失败，不做处理
      } else {
        message.error('操作失败');
      }
    }
  };

  return (
    <div>
      {/* 面包屑导航 */}
      {/* [修复 2026-09-05] 迁移到 antd v5 的 items 写法，消除 Breadcrumb.Item 弃用告警 */}
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link to="/dashboard"><HomeOutlined /> 首页</Link> },
          { title: <Link to="/signage-settings">标识设置</Link> },
          { title: '标识分类' },
        ]}
      />

      {/* 页面标题 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <TagsOutlined style={{ marginRight: 8 }} />
            标识分类设置
          </Title>
          <Text type="secondary">管理标识的分类选项，用于标识分类管理</Text>
        </Col>
        <Col>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新增分类
          </Button>
        </Col>
      </Row>

      {/* 搜索和表格 */}
      <Card>
        <div style={{ marginBottom: 16 }}>
          <Input
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="category-search"
            placeholder="搜索分类名称或编码"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ width: 300 }}
            allowClear
          />
        </div>

        <Table
          columns={columns}
          dataSource={categories}
          rowKey="id"
          loading={loading}
          // [新增 2026-09-17] 固定表格布局：让「描述」列按剩余空间分配并真正省略，
          // 避免长描述把表格撑出容器（auto 布局下 ellipsis 不会生效）
          tableLayout="fixed"
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
        />
      </Card>

      {/* 新增/编辑模态框 */}
      <Modal
        title={editingItem ? '编辑分类' : '新增分类'}
        open={modalVisible}
        onOk={handleModalOk}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        okText="确定"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ is_active: true, shape: 'circle' }}
        >
          <Form.Item
            name="name"
            label="分类名称"
            rules={[{ required: true, message: '请输入分类名称' }]}
          >
            <Input placeholder="请输入分类名称" />
          </Form.Item>
          <Form.Item
            name="code"
            label="分类编码"
            rules={[{ required: true, message: '请输入分类编码' }]}
          >
            <Input placeholder="请输入分类编码（如：DEPT_SIGN）" />
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
          >
            <Input.TextArea placeholder="请输入分类描述" rows={3} />
          </Form.Item>
          {/* [修复 2026-09-05] 新增分类颜色：24 色预设 + 自定义十六进制 */}
          <Form.Item
            name="color"
            label="分类颜色"
            extra="点选预设色板或输入十六进制色值（如 #2F9E64），留空则使用默认色"
          >
            <ColorField />
          </Form.Item>
          {/* [修复 2026-09-05] 新增标记形状：五种形状与分类颜色组合，作为该分类在标识平面图上的标记样式 */}
          <Form.Item
            name="shape"
            label="标记形状"
            initialValue="circle"
            extra="形状与颜色组合后，作为该分类标识在平面图上的标记样式"
          >
            <Select options={MARKER_SHAPES} />
          </Form.Item>
          {/* [新增 2026-09-05] 巡检周期（天）：用于巡检到期/超期预警；留空表示不参与巡检预警 */}
          <Form.Item
            name="inspection_cycle_days"
            label="巡检周期（天）"
            extra="按此周期计算巡检到期/超期预警；留空表示该分类不参与巡检预警"
          >
            <InputNumber min={1} max={3650} style={{ width: '100%' }} placeholder="如 90（选填）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default SignageCategorySettings;
