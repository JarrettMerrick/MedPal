// [修复 2026-09-04] 供应商设置页面：维护制作厂商
import React, { useState, useEffect } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Card, Table, Button, Space, Modal, Form, Input, Select,
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
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
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
  // [调整 2026-09-19] 列宽按库中**实际数据长度**收敛，消除整表横向滚动：
  //   实测 供应商名称 ≤12 字、联系人 3 字、电话 11 位、地址 ≤17 字、邮箱 19 字符，
  //   各列据此给足固定宽度后，仅「地址」不设宽度吸收剩余空间 ——
  //   表格总宽恒等于容器宽度，不再溢出产生横向滚动条。
  //   「地址」同时去掉 ellipsis 并允许跨行：长地址换行完整展示，
  //   而不是被截成省略号（原实现的主要问题）。
  const columns = [
    {
      title: '供应商名称',
      dataIndex: 'name',
      key: 'name',
      // 固定 160px：最长 12 字（南通华宇标识制作有限公司）在此宽度内折为 2 行。
      // （试过「不设宽度交给浏览器按内容比例分配」，结果是名称被更长的地址挤到 3 行，
      //   不如给定宽稳定；地址列承载最长的内容，让它单独吃掉剩余空间更合理。）
      width: 160,
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: '联系人',
      dataIndex: 'contact_person',
      key: 'contact_person',
      width: 72,
    },
    {
      title: '联系电话',
      dataIndex: 'phone',
      key: 'phone',
      width: 112,
    },
    {
      title: '供应商地址',
      dataIndex: 'address',
      key: 'address',
      // 不设 width：作为最长文本列吸收全部剩余空间；允许跨行 + 兜底最小宽度
      // （style 需断言为 CSSProperties，否则 'break-word' 会被推断为 string —— TS2322）
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 140 } as React.CSSProperties,
      }),
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      // 同样不设 width，与地址共享剩余空间；邮箱串本身不含空格，
      // 必须靠 wordBreak 才能断行，否则会把列撑宽并顶出横向滚动条
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 120 } as React.CSSProperties,
      }),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 64,
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
      width: 110,
      // [统一时间口径] 补 render：原实现直接输出后端 UTC 串，比北京时间少 8 小时
      // [调整 2026-09-19] 改为「日期 / 时间」两行展示：整串 19 字符放在窄列里会被
      // 折成三行（2026- / 09-17 / 14:01:43），既难看又占高；两行展示省宽度也好读。
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
      width: 100,
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
