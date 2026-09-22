// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 制度新增/编辑表单（含 RichTextEditor + 类别管理）。
 * [改进] useState → Ant Design Form，手写类别弹窗 → Modal
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { Form, Input, Select, Button, Modal, Card, Space, App, Flex, theme } from 'antd';
import { getRegulation, createRegulation, updateRegulation, getCategories, createCategory, updateCategory, deleteCategory } from '../../api/regulations';
import type { RegulationCategory } from '../../types/regulation';
import RichTextEditor from '../../components/RichTextEditor';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { useToken } = theme;

const RegulationForm: React.FC = () => {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const location = useLocation();
  const { message } = App.useApp();
  const { token } = useToken();
  const [form] = Form.useForm();

  // [改进] 获取来源页面URL，用于返回按钮恢复原始状态
  const returnTo = (location.state as any)?.returnTo as string | undefined;

  const [categories, setCategories] = useState<RegulationCategory[]>([]);
  const [saving, setSaving] = useState(false);
  const [showCatModal, setShowCatModal] = useState(false);
  const [newCatName, setNewCatName] = useState('');
  const [newCatCode, setNewCatCode] = useState('');
  const [catSaving, setCatSaving] = useState(false);
  // [新增] 类别编辑态：editingCatId 控制哪一行正在编辑
  const [editingCatId, setEditingCatId] = useState<number | null>(null);
  const [editingCatName, setEditingCatName] = useState('');
  const [editingCatCode, setEditingCatCode] = useState('');

  const fetchCategories = async () => {
    try { setCategories(await getCategories()); } catch { /* ignore */ }
  };

  useEffect(() => { fetchCategories(); }, []);

  useEffect(() => {
    if (isEdit && id) {
      getRegulation(Number(id)).then((res) => {
        form.setFieldsValue({
          name: res.name,
          category_id: res.category_id || undefined,
          version: res.version || '',
          content: res.content || '',
        });
      });
    }
  }, [id, isEdit, form]);

  const handleSave = async (values: any) => {
    setSaving(true);
    try {
      const data: Record<string, unknown> = { ...values, category_id: values.category_id || null, version: values.version?.trim() || null, content: values.content?.trim() || null };
      if (values.category_id) {
        const cat = categories.find((c) => c.id === values.category_id);
        data.category_name = cat?.name || null;
      }
      if (isEdit && id) await updateRegulation(Number(id), data);
      else await createRegulation(data);
      message.success(isEdit ? '修改成功' : '创建成功');
      navigate(returnTo || '/regulations');
    } catch { message.error('保存失败'); }
    finally { setSaving(false); }
  };

  const handleAddCategory = async () => {
    if (!newCatName.trim()) { message.warning('请输入类别名称'); return; }
    if (!/^[A-Z]{3}$/.test(newCatCode)) { message.warning('类别代码必须为3位大写英文字母'); return; }
    setCatSaving(true);
    try {
      const newCat = await createCategory(newCatName.trim(), newCatCode);
      setCategories((prev) => [...prev, newCat]);
      form.setFieldsValue({ category_id: newCat.id });
      setNewCatName(''); setNewCatCode('');
      setShowCatModal(false);
      message.success('类别添加成功');
    } catch { message.error('添加类别失败'); }
    finally { setCatSaving(false); }
  };

  // [新增] 开始编辑某个类别（名称+代码回填）
  const handleStartEditCategory = (cat: RegulationCategory) => {
    setEditingCatId(cat.id);
    setEditingCatName(cat.name);
    setEditingCatCode(cat.code || '');
  };

  // [新增] 保存编辑的类别
  const handleSaveEditCategory = async (catId: number) => {
    if (!editingCatName.trim()) { message.warning('类别名称不能为空'); return; }
    if (!/^[A-Z]{3}$/.test(editingCatCode)) { message.warning('类别代码必须为3位大写英文字母'); return; }
    setCatSaving(true);
    try {
      const updated = await updateCategory(catId, { name: editingCatName.trim(), code: editingCatCode });
      setCategories((prev) => prev.map((c) => (c.id === catId ? updated : c)));
      setEditingCatId(null);
      message.success('类别已更新');
    } catch { message.error('编辑类别失败'); }
    finally { setCatSaving(false); }
  };

  const handleCancelEdit = () => setEditingCatId(null);

  return (
    <PageContainer maxWidth={800}>
      <PageHeader
        title={isEdit ? '编辑制度' : '新增制度'}
        onBack={() => navigate(returnTo || '/regulations')}
      />

      <Card>
        <Form form={form} layout="vertical" onFinish={handleSave}>
          <Form.Item name="name" label="制度名称" rules={[{ required: true, message: '请输入制度名称' }]}>
            <Input placeholder="请输入制度名称" />
          </Form.Item>

          <Form.Item label="所属类别">
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item name="category_id" noStyle>
                <Select placeholder="请选择类别" allowClear style={{ flex: 1 }} options={categories.map((c) => ({ value: c.id, label: c.name }))} />
              </Form.Item>
              <Button type="primary" ghost onClick={() => setShowCatModal(true)}>管理类别</Button>
            </Space.Compact>
            <Form.Item shouldUpdate noStyle>
              {({ getFieldValue }) => {
                const catId = getFieldValue('category_id');
                if (!catId) return null;
                return (
                  <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>当前：{categories.find((c) => c.id === catId)?.name}</span>
                    <Button type="link" danger size="small" onClick={async () => {
                      try { await deleteCategory(catId); setCategories((p) => p.filter((c) => c.id !== catId)); form.setFieldsValue({ category_id: undefined }); message.success('已删除'); }
                      catch { message.error('删除失败'); }
                    }}>删除该类别</Button>
                  </div>
                );
              }}
            </Form.Item>
          </Form.Item>

          {/* [移除] 版本号由后端自动生成（V{次数}_{类别代码}_{年月日}），前端不再手动输入 */}
          <Form.Item name="content" label="制度内容">
            <RichTextEditor placeholder="请输入制度内容，支持从Word粘贴表格、图片等内容..." />
          </Form.Item>

          <Flex justify="flex-end" gap={12} style={{ paddingTop: 16, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
            <Button onClick={() => navigate(returnTo || '/regulations')}>取消</Button>
            <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
          </Flex>
        </Form>
      </Card>

      {/* 类别管理弹窗：新增（名称+代码）+ 列表（编辑/删除） */}
      <Modal
        open={showCatModal}
        title="管理制度类别"
        onCancel={() => { setShowCatModal(false); setEditingCatId(null); setNewCatName(''); setNewCatCode(''); }}
        footer={null}
        width={520}
      >
        {/* 新增区 */}
        <Space style={{ width: '100%', marginBottom: 12 }}>
          <Input placeholder="类别名称" value={newCatName} onChange={e => setNewCatName(e.target.value)} style={{ width: 180 }} />
          <Input
            placeholder="3位代码"
            value={newCatCode}
            onChange={e => setNewCatCode(e.target.value.toUpperCase())}
            maxLength={3}
            style={{ width: 100, fontFamily: 'monospace', textTransform: 'uppercase' }}
            onPressEnter={handleAddCategory}
          />
          <Button type="primary" onClick={handleAddCategory} loading={catSaving}>添加</Button>
        </Space>

        {/* 列表区 */}
        {categories.length === 0 ? (
          <div style={{ color: token.colorTextQuaternary, fontSize: token.fontSizeSM, textAlign: 'center', padding: 16 }}>暂无类别，请添加</div>
        ) : (
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            {categories.map(cat => (
              <div key={cat.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
                {editingCatId === cat.id ? (
                  <>
                    <Input size="small" value={editingCatName} onChange={e => setEditingCatName(e.target.value)} style={{ flex: 2 }} />
                    <Input size="small" value={editingCatCode} onChange={e => setEditingCatCode(e.target.value.toUpperCase())} maxLength={3} style={{ flex: 1, fontFamily: 'monospace' }} />
                    <Button size="small" type="link" onClick={() => handleSaveEditCategory(cat.id)} loading={catSaving}>保存</Button>
                    <Button size="small" type="link" onClick={handleCancelEdit}>取消</Button>
                  </>
                ) : (
                  <>
                    <span style={{ flex: 2 }}>{cat.name}</span>
                    <span style={{ flex: 1, fontFamily: 'monospace', color: token.colorTextSecondary, fontSize: token.fontSizeSM }}>{cat.code || '-'}</span>
                    <Button size="small" type="link" onClick={() => handleStartEditCategory(cat)}>编辑</Button>
                    <Button size="small" type="link" danger onClick={async () => {
                      try { await deleteCategory(cat.id); setCategories(p => p.filter(c => c.id !== cat.id)); message.success('已删除'); } catch { message.error('删除失败（可能有关联制度）'); }
                    }}>删除</Button>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </PageContainer>
  );
};

export default RegulationForm;
