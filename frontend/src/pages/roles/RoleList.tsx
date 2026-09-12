// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 角色管理 — 严格 RBAC 权限控制页面。
 * [改进] 手写 table/modal/checkbox → Table/Modal/Checkbox/Button
 */

import React, { useEffect, useState } from 'react';
import { usePageParams } from '../../hooks/usePageParams';
import { useCompositionInput } from '../../hooks/useCompositionInput';
import { Table, Button, Input, Select, Modal, Form, Checkbox, Tag, Typography, Space, Card, Alert, App } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { getRoles, createRole, updateRole, deleteRole, getPermissionsByCategory } from '../../api/roles';
import type { Role, PermissionCategory, Permission } from '../../types/role';
import { useAuth } from '../../contexts/AuthContext';
import { hasPermission, PERM_ROLE_CREATE, PERM_ROLE_EDIT, PERM_ROLE_DELETE } from '../../utils/permissions';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text } = Typography;

const scopeLabels: Record<string, string> = { own: '仅本科室', managed: '管辖科室', all: '所有科室' };
const workTypeOptions = [
  { value: 'all', label: '所有工种' }, { value: 'doctor', label: '医生' }, { value: 'nurse', label: '护士' },
  { value: 'technician', label: '技师' }, { value: 'admin', label: '行政' },
];
const PAGE_SIZE = 20;

const RoleList: React.FC = () => {
  const { user } = useAuth();
  const { message, modal } = App.useApp();
  const canCreate = hasPermission(user, PERM_ROLE_CREATE);
  const canEdit = hasPermission(user, PERM_ROLE_EDIT);
  const canDelete = hasPermission(user, PERM_ROLE_DELETE);

  const [roles, setRoles] = useState<Role[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editRole, setEditRole] = useState<Role | null>(null);
  const [permCategories, setPermCategories] = useState<PermissionCategory[]>([]);
  const [viewOnly, setViewOnly] = useState(false);

  const { params, setParam } = usePageParams({
    page: '1',
    search: '',
  });

  const page = Number(params.page);
  const search = params.search;

  // 使用 useCompositionInput 处理 IME 输入
  const {
    value: searchInputValue,
    handleChange: handleSearchChange,
    handleCompositionStart,
    handleCompositionEnd,
  } = useCompositionInput(search, (v) => setParam('search', v));

  const [form, setForm] = useState({
    name: '', display_name: '', description: '',
    department_scope: 'own' as string, work_type_scope: 'all' as string,
    permission_ids: [] as number[],
  });

  const selectedWorkTypes = form.work_type_scope === 'all' ? [] : form.work_type_scope.split(',').filter(Boolean);

  const fetchData = async () => {
    setLoading(true);
    try { const res = await getRoles({ page, page_size: PAGE_SIZE, search: search || undefined }); setRoles(res.items); setTotal(res.total); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); getPermissionsByCategory().then(setPermCategories).catch(() => {}); }, [page, search]);

  const handleSearch = () => { setParam('page', '1'); };

  const openCreate = () => {
    if (!canCreate) return;
    setEditRole(null); setViewOnly(false);
    setForm({ name: '', display_name: '', description: '', department_scope: 'own', work_type_scope: 'all', permission_ids: [] });
    setShowForm(true);
  };

  const openEdit = (role: Role) => {
    setEditRole(role); setViewOnly(!canEdit);
    setForm({ name: role.name, display_name: role.display_name, description: role.description || '', department_scope: role.department_scope || 'own', work_type_scope: role.work_type_scope || 'all', permission_ids: role.permissions.map(p => p.id) });
    setShowForm(true);
  };

  const togglePermission = (permId: number) => {
    if (viewOnly) return;
    setForm(prev => ({ ...prev, permission_ids: prev.permission_ids.includes(permId) ? prev.permission_ids.filter(id => id !== permId) : [...prev.permission_ids, permId] }));
  };

  const toggleCategory = (perms: Permission[], select: boolean) => {
    if (viewOnly) return;
    const ids = perms.map(p => p.id);
    setForm(prev => ({ ...prev, permission_ids: select ? [...new Set([...prev.permission_ids, ...ids])] : prev.permission_ids.filter(id => !ids.includes(id)) }));
  };

  const handleSubmit = async () => {
    if (viewOnly) return;
    try {
      if (editRole) await updateRole(editRole.id, { display_name: form.display_name, description: form.description || undefined, department_scope: form.department_scope, work_type_scope: form.work_type_scope, permission_ids: form.permission_ids });
      else await createRole({ name: form.name, display_name: form.display_name, description: form.description || undefined, department_scope: form.department_scope, work_type_scope: form.work_type_scope, permission_ids: form.permission_ids });
      setShowForm(false); fetchData();
    } catch (err: unknown) { message.error((err as any)?.response?.data?.detail || '操作失败'); }
  };

  const handleDelete = (role: Role) => {
    if (!canDelete) return;
    if (role.is_system) { message.warning('系统预设角色不可删除'); return; }
    modal.confirm({
      title: `确定要删除角色"${role.display_name}"吗？`,
      onOk: async () => { try { await deleteRole(role.id); fetchData(); } catch (err: unknown) { message.error((err as any)?.response?.data?.detail || '删除失败'); } },
    });
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '角色标识', dataIndex: 'name', render: (v: string) => <Tag>{v}</Tag> },
    { title: '显示名称', dataIndex: 'display_name', render: (v: string) => <Text strong>{v}</Text> },
    { title: '科室范围', dataIndex: 'department_scope', render: (v: string) => <Tag>{scopeLabels[v] || v || '所有科室'}</Tag> },
    { title: '工种范围', dataIndex: 'work_type_scope', render: (v: string) => <Tag color="blue">{v === 'all' ? '所有工种' : v}</Tag> },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '类型', dataIndex: 'is_system', render: (v: boolean) => <Tag color={v ? 'blue' : 'green'}>{v ? '系统预设' : '自定义'}</Tag> },
    { title: '权限数', dataIndex: 'permissions', render: (v: Permission[]) => v.length },
    ...(canEdit || canDelete ? [{
      title: '操作', key: 'actions', width: 120,
      render: (_: any, r: Role) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openEdit(r)}>{canEdit ? '编辑' : '查看'}</Button>
          {canDelete && !r.is_system && <Button type="link" danger size="small" onClick={() => handleDelete(r)}>删除</Button>}
        </Space>
      ),
    }] : []),
  ];

  return (
    <PageContainer>
      <PageHeader
        title="角色管理"
        extra={canCreate
          ? <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增角色</Button>
          : <Text type="secondary" style={{ fontSize: 12 }}>暂无新增权限</Text>}
      />

      <Card style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="role-search"
            placeholder="搜索角色名称..."
            value={searchInputValue} 
            onChange={handleSearchChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            onPressEnter={handleSearch} 
            allowClear 
          />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </Space.Compact>
      </Card>

      <Table dataSource={roles} columns={columns} rowKey="id" loading={loading}
        pagination={{ current: page, total, pageSize: PAGE_SIZE, onChange: (p) => setParam('page', String(p)), showTotal: t => `共 ${t} 条` }} />

      {/* 表单 Modal */}
      <Modal open={showForm} onCancel={() => setShowForm(false)} footer={null} width={700}
        title={editRole ? (viewOnly ? `查看角色：${editRole.display_name}` : '编辑角色') : '新增角色'}>
        {viewOnly && <Alert message="您没有编辑权限，当前为只读查看模式。如需修改请联系超级管理员。" type="warning" showIcon style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={handleSubmit}>
          {!editRole && (
            <Form.Item label="角色标识" required><Input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="英文标识，如 senior_doctor" disabled={viewOnly} /></Form.Item>
          )}
          {editRole && (
            <Form.Item label="角色标识"><Input value={form.name} disabled /><Text type="secondary" style={{ fontSize: 12 }}>角色标识创建后不可修改</Text></Form.Item>
          )}
          <Form.Item label="显示名称" required><Input value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} disabled={viewOnly} /></Form.Item>
          <Form.Item label="描述"><Input.TextArea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} rows={2} disabled={viewOnly} /></Form.Item>
          <Card size="small" title="数据范围配置" style={{ marginBottom: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div>
                <Text style={{ fontSize: 12, color: '#666' }}>科室数据范围</Text>
                <Select value={form.department_scope} onChange={v => setForm({ ...form, department_scope: v })} disabled={viewOnly} style={{ width: '100%', marginTop: 4 }}
                  options={[{ value: 'own', label: '仅本科室' }, { value: 'managed', label: '管辖科室' }, { value: 'all', label: '所有科室' }]} />
              </div>
              <div>
                <Text style={{ fontSize: 12, color: '#666' }}>工种数据范围</Text>
                <Checkbox.Group options={workTypeOptions.filter(o => o.value !== 'all')} value={selectedWorkTypes} disabled={viewOnly}
                  onChange={(vals) => setForm({ ...form, work_type_scope: (vals as string[]).length === 0 ? 'all' : (vals as string[]).join(',') })} style={{ marginTop: 4 }} />
                <Checkbox checked={form.work_type_scope === 'all'} onChange={e => setForm({ ...form, work_type_scope: e.target.checked ? 'all' : '' })} disabled={viewOnly}>所有工种</Checkbox>
              </div>
            </div>
          </Card>
          <Card size="small" title="权限配置" style={{ marginBottom: 16 }}>
            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
              {permCategories.map(cat => {
                const ids = cat.permissions.map(p => p.id);
                const allSelected = ids.every(id => form.permission_ids.includes(id));
                const someSelected = ids.some(id => form.permission_ids.includes(id));
                return (
                  <div key={cat.category} style={{ marginBottom: 12 }}>
                    <Checkbox checked={allSelected} indeterminate={someSelected && !allSelected} disabled={viewOnly}
                      onChange={e => toggleCategory(cat.permissions, e.target.checked)}>
                      <Text strong>{cat.category_label}</Text>
                    </Checkbox>
                    <div style={{ marginLeft: 24, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                      {cat.permissions.map(perm => (
                        <Checkbox key={perm.id} checked={form.permission_ids.includes(perm.id)} disabled={viewOnly}
                          onChange={() => togglePermission(perm.id)}>{perm.display_name}</Checkbox>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>已选 {form.permission_ids.length} 项权限</Text>
              {!viewOnly && (
                <Button type="link" size="small" onClick={() => {
                  const allIds = permCategories.flatMap(c => c.permissions.map(p => p.id));
                  setForm(prev => ({ ...prev, permission_ids: prev.permission_ids.length === allIds.length ? [] : allIds }));
                }}>{form.permission_ids.length === permCategories.flatMap(c => c.permissions).length ? '取消全选' : '全选'}</Button>
              )}
            </div>
          </Card>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
            <Button onClick={() => setShowForm(false)}>{viewOnly ? '关闭' : '取消'}</Button>
            {!viewOnly && <Button type="primary" htmlType="submit">{editRole ? '保存修改' : '创建角色'}</Button>}
          </div>
        </Form>
      </Modal>
    </PageContainer>
  );
};

export default RoleList;
