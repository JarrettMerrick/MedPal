// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 用户管理页（卡片式 + 编辑/科室关联 Modal），含批量创建 + 科室权限树。
 * [改进] 手写 card/modal/input/select → Card/Modal/Input/Select/Button/Pagination
 */

import React, { useEffect, useState } from 'react';
import { usePageParams } from '../../hooks/usePageParams';
import { useCompositionInput } from '../../hooks/useCompositionInput';
import { Card, Row, Col, Button, Input, Select, Modal, Form, Tag, Typography, Pagination, Spin, Space, App, Flex, theme, Checkbox, Tooltip } from 'antd';
import { PlusOutlined, EditOutlined, ApartmentOutlined, KeyOutlined, StopOutlined, CheckCircleOutlined, DeleteOutlined, UsergroupAddOutlined } from '@ant-design/icons';
import { getUsers, createUser, updateUser, resetPassword, deleteUser, batchCreateFromStaff } from '../../api/users';
import { createStaff } from '../../api/staff';
import { getAllDepartments } from '../../api/departments';
import { getAllRoles } from '../../api/roles';
import { getUserDepartmentScope, updateUserDepartmentScope } from '../../api/userDepartmentScope';
import type { UserItem } from '../../types/user';
import type { RoleOption } from '../../types/role';
// [修复 2026-09-02] P3: 导入统一错误处理函数
import { getErrorMessage } from '../../utils/format';
import { getRoleLabel } from '../../utils/roles';
import DepartmentTreeSelect from '../../components/DepartmentTreeSelect';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text, Title } = Typography;
const { useToken } = theme;
const DEFAULT_PAGE_SIZE = 12;

// [改进] 角色徽章改用 antd Tag 语义色（替代硬编码 hex）
function getRoleTagColor(role: string): string {
  const map: Record<string, string> = {
    admin_manager: 'red',
    dept_manager: 'orange',
    employee: 'default',
  };
  return map[role] || 'default';
}

// [改进] 卡片顶部色条：普通员工(employee)绿色，其他角色橙色
function getCardTopColor(role: string, success: string, warning: string): string {
  return role === 'employee' ? success : warning;
}

const UserManage: React.FC = () => {
  const { message, modal } = App.useApp();
  const { token } = useToken();
  // 列表
  const [users, setUsers] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const { params, setParam, setParams } = usePageParams({
    page: '1',
    page_size: String(DEFAULT_PAGE_SIZE),
    search: '',
    role: '',
    has_profile: '',
  });

  const page = Number(params.page);
  const pageSize = Number(params.page_size);
  const search = params.search;
  const roleFilter = params.role;
  const hasProfileFilter = params.has_profile;

  // 使用 useCompositionInput 处理 IME 输入
  const {
    value: searchInputValue,
    handleChange: handleSearchChange,
    handleCompositionStart,
    handleCompositionEnd,
  } = useCompositionInput(search, (v) => setParam('search', v));

  // 用户表单
  const [showUserForm, setShowUserForm] = useState(false);
  const [editUser, setEditUser] = useState<UserItem | null>(null);
  const [formSaving, setFormSaving] = useState(false);
  // 批量创建
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchResult, setBatchResult] = useState<{ created: number; skipped: number } | null>(null);
  // 科室权限
  const [showDeptScope, setShowDeptScope] = useState(false);
  const [scopeUser, setScopeUser] = useState<UserItem | null>(null);
  const [deptScopeLoading, setDeptScopeLoading] = useState(false);
  const [deptScopeSelectedIds, setDeptScopeSelectedIds] = useState<number[]>([]);
  // 基础数据
  const [departments, setDepartments] = useState<{ id: number; name: string; category: string }[]>([]);
  const [roles, setRoles] = useState<RoleOption[]>([]);

  const [userForm, setUserForm] = useState({ employee_id: '', name: '', role: 'employee', role_id: '' as string | number, department: '', user_type: 'admin_user' });
  // [新增] 是否勾选"同步到人员管理"
  const [syncToStaff, setSyncToStaff] = useState(false);

  const fetchUsers = async () => {
    setLoading(true);
    try { const res = await getUsers({ page, page_size: pageSize, search: search || undefined, role: roleFilter || undefined, has_profile: hasProfileFilter || undefined }); setUsers(res.items); setTotal(res.total); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchUsers(); getAllDepartments().then(setDepartments).catch(() => {}); getAllRoles().then(setRoles).catch(() => {}); }, [page, pageSize, roleFilter, search, hasProfileFilter]);

  const handleSearch = () => { setParam('page', '1'); };

  const openCreateUser = () => {
    setEditUser(null);
    setUserForm({ employee_id: '', name: '', role: 'employee', role_id: '', department: '', user_type: 'admin_user' });
    setSyncToStaff(false);
    setShowUserForm(true);
  };

  const openEditUser = (u: UserItem) => {
    setEditUser(u);
    setUserForm({ employee_id: u.employee_id, name: u.name, role: u.role, role_id: (u as any).role_id || '', department: u.department || '', user_type: u.user_type });
    setShowUserForm(true);
  };

  const handleUserSubmit = async () => {
    setFormSaving(true);
    try {
      const payload: Record<string, unknown> = { ...userForm, department: userForm.department || null, role_id: userForm.role_id !== '' ? Number(userForm.role_id) : null };
      if (editUser) await updateUser(editUser.employee_id, payload);
      else {
        await createUser(payload);
        // [新增] 勾选"同步到人员管理"时，创建对应的 staff 记录
        if (syncToStaff) {
          try {
            await createStaff({
              employee_id: userForm.employee_id,
              name: userForm.name,
              work_type: 'admin' as const,
              department: userForm.department || '',
              education: '', title: '', position: '',
              expertise_short: '', expertise_standard: '',
              social_appointments: '', honors: '', remarks: '',
            } as any);
          } catch { /* 人员创建失败不阻断主流程 */ }
        }
      }
      setShowUserForm(false); fetchUsers();
    } catch (err: unknown) { message.error(getErrorMessage(err)); }
    finally { setFormSaving(false); }
  };

  const handleResetPassword = (id: string) => {
    modal.confirm({
      title: `确定要重置用户 ${id} 的密码吗？`,
      onOk: async () => {
        try {
          const res = await resetPassword(id);
          // [修复] 新密码由服务端随机生成，必须展示真实返回值。
          // 原先前端硬编码提示 "123456"，与库里实际写入的随机强口令不符，
          // 导致管理员把错误密码告知使用者、用户始终无法登录。
          // 用 App 实例而非静态 Modal.success，避免 antd 的 context 警告
          modal.success({
            title: '密码已重置',
            content: (
              <div>
                <div>新密码：<Text strong copyable code>{res.password}</Text></div>
                <div style={{ marginTop: 8, color: 'var(--text-3)' }}>
                  请将该密码告知使用者，其首次登录时会被强制修改。
                </div>
              </div>
            ),
          });
        } catch (err: unknown) {
          message.error(getErrorMessage(err, '重置失败'));
        }
      },
    });
  };

  const handleToggleActive = async (u: UserItem) => {
    try { await updateUser(u.employee_id, { is_active: !u.is_active }); fetchUsers(); }
    catch (err: unknown) { message.error(getErrorMessage(err)); }
  };

  const handleDeleteUser = (u: UserItem) => {
    modal.confirm({
      title: `确定要删除用户 ${u.name}（${u.employee_id}）吗？`,
      content: '删除后不可恢复。',
      okType: 'danger',
      onOk: async () => { try { await deleteUser(u.employee_id); fetchUsers(); } catch (err: unknown) { message.error(getErrorMessage(err, '删除失败')); } },
    });
  };

  const handleBatchCreate = async () => {
    setBatchLoading(true);
    try { const res = await batchCreateFromStaff(); setBatchResult({ created: res.created, skipped: res.skipped }); fetchUsers(); }
    catch (err: unknown) { message.error(getErrorMessage(err, '批量创建失败')); }
    finally { setBatchLoading(false); }
  };

  // 科室权限
  const openDeptScope = async (u: UserItem) => {
    setScopeUser(u); setShowDeptScope(true); setDeptScopeLoading(true);
    try { const res = await getUserDepartmentScope(u.employee_id); setDeptScopeSelectedIds(res.items.map(i => i.department_id)); }
    catch { setDeptScopeSelectedIds([]); }
    finally { setDeptScopeLoading(false); }
  };

  const handleSaveDeptScope = async () => {
    if (!scopeUser) return;
    try { setDeptScopeLoading(true); await updateUserDepartmentScope(scopeUser.employee_id, deptScopeSelectedIds); setShowDeptScope(false); setScopeUser(null); }
    catch (err: unknown) { message.error(getErrorMessage(err, '保存失败')); }
    finally { setDeptScopeLoading(false); }
  };

  return (
    <PageContainer>
      <PageHeader
        title="用户管理"
        extra={(
          <Space>
            <Button icon={<UsergroupAddOutlined />} onClick={handleBatchCreate} loading={batchLoading}>一键生成员工账号</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateUser}>新增用户</Button>
          </Space>
        )}
      />

      <Card style={{ marginBottom: token.marginLG }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
            id="user-search"
            placeholder="搜索工号或姓名..."
            value={searchInputValue} 
            onChange={handleSearchChange}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            onPressEnter={handleSearch} 
            allowClear 
          />
          <Select value={roleFilter || undefined} onChange={v => setParams({ role: v || '', page: '1' })} placeholder="全部角色" style={{ minWidth: 140 }}
            options={roles.map(r => ({ value: r.name, label: r.display_name }))} allowClear />
          <Select value={hasProfileFilter || undefined} onChange={v => setParams({ has_profile: v || '', page: '1' })} placeholder="人员简介" style={{ minWidth: 130 }}
            options={[{ value: 'false', label: '无简介用户' }, { value: 'true', label: '有简介用户' }]} allowClear />
          <Button type="primary" onClick={handleSearch}>搜索</Button>
        </Space.Compact>
      </Card>

      {loading ? <Flex justify="center" style={{ padding: token.paddingLG * 3 }}><Spin size="large" /></Flex> : users.length === 0 ? (
        <Flex justify="center" style={{ padding: token.paddingLG * 3, color: token.colorTextTertiary }}>暂无数据</Flex>
      ) : (
        <>
          <Row gutter={[token.marginMD, token.marginMD]}>
            {users.map(u => (
              <Col key={u.employee_id} xs={24} sm={12} lg={8} xl={6}>
                <Card hoverable size="small" style={{ borderTop: `3px solid ${getCardTopColor(u.role, token.colorSuccess, token.colorWarning)}` }}
                  actions={[
                    <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEditUser(u)} key="edit">编辑</Button>,
                    <Button type="text" size="small" icon={<ApartmentOutlined />} onClick={() => openDeptScope(u)} key="dept">科室</Button>,
                    <Button type="text" size="small" icon={<KeyOutlined />} onClick={() => handleResetPassword(u.employee_id)} key="pwd">重置</Button>,
                  ]}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <Text strong>{u.name}</Text>
                    <Tag color={getRoleTagColor(u.role)}>{getRoleLabel(u.role)}</Tag>
                  </div>
                  <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block' }}>{u.employee_id}</Text>
                  <Space size={token.marginXS} style={{ marginTop: token.marginXS }} wrap>
                    {u.department && <Tag>{u.department}</Tag>}
                    <Tag>{u.user_type === 'doctor' ? '医生' : u.user_type === 'nurse' ? '护士' : '管理员'}</Tag>
                    <Tag color={u.is_active ? 'green' : 'red'}>{u.is_active ? '启用' : '禁用'}</Tag>
                  </Space>
                  <div style={{ display: 'flex', gap: token.marginXS, marginTop: token.marginSM }}>
                    {/* [新增 2026-09-10] 系统须始终保留至少一个超级管理员：
                        最后一个超级管理员不允许被禁用（仍可保持启用）与删除。
                        用 span 包裹以免 disabled 按钮无法触发 Tooltip 提示。 */}
                    <Tooltip title={u.is_last_super_admin && u.is_active ? '系统须保留至少一个超级管理员，不可禁用' : undefined}>
                      <span style={{ display: 'inline-block' }}>
                        <Button size="small" danger={u.is_active}
                          disabled={u.is_active && !!u.is_last_super_admin}
                          onClick={() => handleToggleActive(u)}
                          icon={u.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
                        >{u.is_active ? '禁用' : '启用'}</Button>
                      </span>
                    </Tooltip>
                    <Tooltip title={u.is_last_super_admin ? '系统须保留至少一个超级管理员，不可删除' : undefined}>
                      <span style={{ display: 'inline-block' }}>
                        <Button size="small" danger icon={<DeleteOutlined />} disabled={!!u.is_last_super_admin} onClick={() => handleDeleteUser(u)}>删除</Button>
                      </span>
                    </Tooltip>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
          {total > 0 && (
            <Flex justify="center" style={{ marginTop: token.marginLG }}>
              <Pagination 
                current={page} 
                total={total} 
                pageSize={pageSize} 
                onChange={(p, ps) => { if (ps !== pageSize) { setParams({ page: '1', page_size: String(ps) }); } else { setParam('page', String(p)); } }}
                showTotal={(t) => `共 ${t} 个用户`} 
                showSizeChanger={true}
                pageSizeOptions={['12', '24', '48', '96']}
              />
            </Flex>
          )}
        </>
      )}

      {/* 用户编辑/新增 Modal */}
      <Modal open={showUserForm} onCancel={() => setShowUserForm(false)} footer={null} title={editUser ? '编辑用户' : '新增用户'}>
        <Form layout="vertical" onFinish={handleUserSubmit}>
          <Form.Item label="工号" required help={userForm.role !== 'admin_manager' && !/^\d{6}$/.test(userForm.employee_id) && userForm.employee_id ? '工号须为6位数字（超级管理员除外）' : ''} validateStatus={!editUser && userForm.role !== 'admin_manager' && userForm.employee_id && !/^\d{6}$/.test(userForm.employee_id) ? 'error' : ''}>
            <Input value={userForm.employee_id} onChange={e => setUserForm({ ...userForm, employee_id: e.target.value })} disabled={!!editUser} maxLength={userForm.role === 'admin_manager' ? undefined : 6} placeholder={userForm.role === 'admin_manager' ? '超级管理员无限制' : '6位数字工号'} />
          </Form.Item>
          <Form.Item label="姓名" required><Input value={userForm.name} onChange={e => setUserForm({ ...userForm, name: e.target.value })} /></Form.Item>
          {/* [新增 2026-09-10] 最后一个超级管理员不允许降级为其他角色（后端同样强制校验） */}
          <Form.Item label="角色" help={editUser?.is_last_super_admin ? '系统须保留至少一个超级管理员，不可变更该账号角色' : ''}>
            <Select value={userForm.role} disabled={!!editUser?.is_last_super_admin} onChange={v => {
              const matched = roles.find(r => r.name === v); setUserForm(prev => ({ ...prev, role: v, role_id: matched ? String(matched.id) : '' }));
            }} options={roles.map(r => ({ value: r.name, label: r.display_name }))} />
          </Form.Item>
          <Form.Item label="科室"><Select value={userForm.department || undefined} onChange={v => setUserForm({ ...userForm, department: v || '' })} allowClear placeholder="请选择科室" options={departments.map(d => ({ value: d.name, label: d.name }))} /></Form.Item>
          <Form.Item label="用户类型"><Select value={userForm.user_type} onChange={v => setUserForm({ ...userForm, user_type: v })} options={[{ value: 'admin_user', label: '管理员' }, { value: 'doctor', label: '医生' }, { value: 'nurse', label: '护士' }]} /></Form.Item>
          {/* [新增] 仅新增模式显示"同步到人员管理"勾选框 */}
          {!editUser && (
            <Form.Item><Checkbox checked={syncToStaff} onChange={e => setSyncToStaff(e.target.checked)}>同时添加到人员管理列表</Checkbox></Form.Item>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: token.marginMD, paddingTop: token.paddingMD }}>
            <Button onClick={() => setShowUserForm(false)}>取消</Button>
            <Button type="primary" htmlType="submit" loading={formSaving}>确定</Button>
          </div>
        </Form>
      </Modal>

      {/* 科室权限关联 Modal */}
      <Modal open={showDeptScope} onCancel={() => { setShowDeptScope(false); setScopeUser(null); setDeptScopeSelectedIds([]); }} footer={null} width={520}
        title={<>科室权限范围管理 <Text type="secondary" style={{ fontSize: token.fontSizeSM, fontWeight: 'normal' }}>{scopeUser?.name}（{scopeUser?.employee_id}）</Text></>}>
        <div style={{ maxHeight: '55vh', overflowY: 'auto', marginBottom: token.marginMD }}>
          {deptScopeLoading ? <Flex justify="center" style={{ padding: token.paddingLG }}><Spin /></Flex> : (
            <DepartmentTreeSelect departments={departments} selectedIds={deptScopeSelectedIds} onChange={setDeptScopeSelectedIds} />
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: token.marginMD, paddingTop: token.paddingMD, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
          <Button onClick={() => { setShowDeptScope(false); setScopeUser(null); setDeptScopeSelectedIds([]); }}>取消</Button>
          <Button type="primary" onClick={handleSaveDeptScope} loading={deptScopeLoading}>保存</Button>
        </div>
      </Modal>

      {/* 批量生成结果 */}
      <Modal open={!!batchResult} onCancel={() => setBatchResult(null)} footer={null} centered width={360}>
        {batchResult && (
          <div style={{ textAlign: 'center', padding: `0 ${token.paddingMD}` }}>
            <CheckCircleOutlined style={{ fontSize: 48, color: token.colorSuccess, marginBottom: token.marginMD }} />
            <Title level={5}>批量生成完成</Title>
            <p>成功创建 <Text strong style={{ color: token.colorSuccess }}>{batchResult.created}</Text> 个账号</p>
            <p>跳过 <Text strong type="secondary">{batchResult.skipped}</Text> 个已存在的账号</p>
            <Button type="primary" block style={{ marginTop: 16 }} onClick={() => setBatchResult(null)}>确定</Button>
          </div>
        )}
      </Modal>
    </PageContainer>
  );
};

export default UserManage;
