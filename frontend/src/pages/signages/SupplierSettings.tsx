// [修复 2026-09-04] 供应商设置页面：维护制作厂商
import React, { useState, useEffect } from 'react';
import {
  Card, Table, Button, Space, Modal, Form, Input, Select, message,
  Popconfirm, Tag, Breadcrumb, Typography, Row, Col, Tabs, Switch
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, SearchOutlined,
  HomeOutlined, TeamOutlined, ShopOutlined, ToolOutlined
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { getSuppliers, createSupplier, updateSupplier, deleteSupplier } from '../../api/signage-settings';
import type { Supplier } from '../../api/signage-settings';
// [统一时间口径] 时间展示一律走 utils/time（原 updated_at 列未加 render，直接把 UTC 原值显示出来）
import { formatDateTimeStandard } from '../../utils/time';

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;

// [修复 2026-09-04] 供应商设置页面组件
const SupplierSettings: React.FC = () => {
  // 状态管理
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [modalVisible, setModalVisible] = useState(false);
  const [editingItem, setEditingItem] = useState<Supplier | null>(null);
  const [form] = Form.useForm();

  // [修复 2026-09-04] 从后端API加载供应商数据
  const loadSuppliers = async () => {
    setLoading(true);
    try {
      const result = await getSuppliers({ page: 1, page_size: 100, search: searchText || undefined });
      setSuppliers(result.items);
    } catch {
      message.error('获取供应商列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSuppliers();
  }, []);

  // 搜索变化时重新加载
  useEffect(() => {
    loadSuppliers();
  }, [searchText]);

  // [修复 2026-09-04] 表格列定义
  const columns = [
    {
      title: '供应商名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: '联系人',
      dataIndex: 'contact_person',
      key: 'contact_person',
    },
    {
      title: '联系电话',
      dataIndex: 'phone',
      key: 'phone',
    },
    {
      title: '地址',
      dataIndex: 'address',
      key: 'address',
      ellipsis: true,
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
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
      width: 160,
      // [统一时间口径] 补 render：原实现直接输出后端 UTC 串，比北京时间少 8 小时
      render: (v: string) => (v ? formatDateTimeStandard(v) : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: any, record: Supplier) => (
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
            title="确定要删除这个供应商吗？"
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

  // [修复 2026-09-04] 数据已通过API加载并按搜索过滤

  // [修复 2026-09-04] 处理新增/编辑
  const handleAdd = () => {
    setEditingItem(null);
    form.resetFields();
    form.setFieldsValue({ type: 'manufacturer' });
    setModalVisible(true);
  };

  const handleEdit = (record: Supplier) => {
    setEditingItem(record);
    form.setFieldsValue(record);
    setModalVisible(true);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteSupplier(id);
      message.success('删除成功');
      loadSuppliers();
    } catch {
      message.error('删除失败');
    }
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingItem) {
        // 编辑模式
        await updateSupplier(editingItem.id, values);
        message.success('编辑成功');
      } else {
        // 新增模式
        await createSupplier({ ...values, is_active: true } as any);
        message.success('新增成功');
      }
      setModalVisible(false);
      form.resetFields();
      loadSuppliers();
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) {
        // 表单验证失败，不做处理
      } else {
        message.error('操作失败');
      }
    }
  };

  // [修复 2026-09-04] 获取当前类型的图标
  const getTypeIcon = (type: string) => {
    return <ShopOutlined />;
  };

  // [修复 2026-09-04] 获取当前类型的中文名称
  const getTypeName = (type: string) => {
    return '制作厂商';
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
          { title: '供应商设置' },
        ]}
      />

      {/* 页面标题 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <TeamOutlined style={{ marginRight: 8 }} />
            供应商设置
          </Title>
          <Text type="secondary">管理标识制作厂商信息</Text>
        </Col>
        <Col>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            新增供应商
          </Button>
        </Col>
      </Row>

      {/* 搜索和表格 */}
      <Card>
        <div style={{ marginBottom: 16 }}>
          <Input
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="supplier-search"
            placeholder="搜索供应商名称或联系人"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ width: 300 }}
            allowClear
          />
        </div>

        <Table
          columns={columns}
          dataSource={suppliers}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
        />
      </Card>

      {/* 新增/编辑模态框 */}
      <Modal
        title={editingItem ? `编辑${getTypeName('')}` : `新增${getTypeName('')}`}
        open={modalVisible}
        onOk={handleModalOk}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
        }}
        okText="确定"
        cancelText="取消"
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ type: 'manufacturer', is_active: true }}
        >
          <Form.Item
            name="type"
            label="供应商类型"
            hidden
          >
            <Select disabled>
              <Option value="manufacturer">制作厂商</Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="name"
            label="供应商名称"
            rules={[{ required: true, message: '请输入供应商名称' }]}
          >
            <Input placeholder="请输入供应商名称" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="contact_person"
                label="联系人"
              >
                <Input placeholder="请输入联系人" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="phone"
                label="联系电话"
              >
                <Input placeholder="请输入联系电话" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="address"
            label="地址"
          >
            <Input placeholder="请输入地址" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
          >
            <Input placeholder="请输入邮箱" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default SupplierSettings;
