// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 标签管理弹窗：按维度（项目 / 类型 / 状态…）组织标签的增删改。
 *
 * [新增 2026-09-17] 需求：允许为文件添加、修改、移除标签，便于多维度归集。
 * 交互：左侧按「维度」分组展示标签与使用计数；支持新建维度、改标签名/维度/颜色；
 * 删除标签会解除其与文件的关联（不影响文件本身）。
 */
import React, { useMemo, useState } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Button, Form, Input, Modal, Popconfirm, Select, Space, Tag, Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';

import { createFileTag, deleteFileTag, updateFileTag } from '../../../api/designFiles';
import type { FileTag } from '../../../api/designFiles';

const { Text } = Typography;

/** 常用维度建议（仍允许自由输入，保持灵活性） */
const GROUP_SUGGESTIONS = ['项目', '类型', '状态', '适用科室', '整理状态'];

interface TagManagerModalProps {
  open: boolean;
  tags: FileTag[];
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}

const TagManagerModal: React.FC<TagManagerModalProps> = ({
  open, tags, canEdit, onClose, onChanged,
}) => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  const [editing, setEditing] = useState<FileTag | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const grouped = useMemo(() => {
    const map = new Map<string, FileTag[]>();
    tags.forEach((tag) => {
      const list = map.get(tag.group_name) || [];
      list.push(tag);
      map.set(tag.group_name, list);
    });
    return Array.from(map.entries());
  }, [tags]);

  // [修复 2026-09-17] 维度字段使用 Select mode="tags"：组件值必须是**数组**。
  // 约定：表单内 group_name 存数组（交互用），提交时归一化为字符串（与后端一致）；
  // 回显时把后端字符串包装成数组，否则编辑已有标签时维度会显示为空。
  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ group_name: ['项目'] });
    setModalOpen(true);
  };

  const openEdit = (tag: FileTag) => {
    setEditing(tag);
    form.setFieldsValue({ name: tag.name, group_name: [tag.group_name], color: tag.color });
    setModalOpen(true);
  };

  const submit = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      // [修复 2026-09-17] 归一化后再提交：mode="tags" 的 Select 返回数组（["项目"]），
      // 而后端 name / group_name 均为字符串，直接提交会导致 422（请求参数校验失败）
      const groupValues = Array.isArray(values.group_name) ? values.group_name : [values.group_name];
      const payload = {
        name: String(values.name ?? '').trim(),
        group_name: String(groupValues[0] ?? '').trim() || '通用',
        color: String(values.color ?? '').trim() || undefined,
      };
      if (editing) {
        await updateFileTag(editing.id, payload);
        message.success('标签已更新');
      } else {
        await createFileTag(payload);
        message.success('标签已创建');
      }
      setModalOpen(false);
      onChanged();
    } catch (error: any) {
      if (error?.errorFields) return; // 表单自身校验失败，已有行内提示
      // [修复 2026-09-17] FastAPI 422 的 detail 是数组（逐字段错误），
      // 原实现直接当字符串输出会显示 [object Object]，这里统一转成可读文案
      const detail = error?.response?.data?.detail;
      const text = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: any) => item?.msg).filter(Boolean).join('；')
          : '';
      message.error(text || '操作失败');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (tag: FileTag) => {
    try {
      await deleteFileTag(tag.id);
      message.success('标签已删除');
      onChanged();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败');
    }
  };

  return (
    <Modal
      title="标签管理"
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={680}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text type="secondary">
          标签按维度分组（如 项目 / 类型 / 状态），同一维度内名称唯一；可按维度多选筛选文件。
        </Text>
        {canEdit && (
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreate}>
            新建标签
          </Button>
        )}
      </div>

      {grouped.length === 0 ? (
        <Text type="secondary">暂无标签，点击「新建标签」创建（例如：维度=项目，名称=门诊改造）</Text>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={14}>
          {grouped.map(([group, groupTags]) => (
            <div key={group}>
              <Text strong>{group}</Text>
              <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {groupTags.map((tag) => (
                  <Tag
                    key={tag.id}
                    color={tag.color || 'default'}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, paddingInline: 8 }}
                  >
                    {tag.name}
                    <Text style={{ fontSize: 12, color: 'inherit', opacity: 0.75 }}>{tag.file_count}</Text>
                    {canEdit && (
                      <>
                        <EditOutlined
                          style={{ cursor: 'pointer' }}
                          onClick={() => openEdit(tag)}
                        />
                        <Popconfirm
                          title={`删除标签「${tag.name}」？`}
                          description="将解除该标签与文件的关联，不影响文件本身。"
                          okText="确认删除"
                          cancelText="取消"
                          onConfirm={() => remove(tag)}
                        >
                          <DeleteOutlined style={{ cursor: 'pointer' }} />
                        </Popconfirm>
                      </>
                    )}
                  </Tag>
                ))}
              </div>
            </div>
          ))}
        </Space>
      )}

      <Modal
        title={editing ? '编辑标签' : '新建标签'}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="group_name"
            label="标签维度"
            rules={[{ required: true, message: '请选择或输入维度' }]}
            extra="维度用于把标签分组，例如「项目」「类型」「状态」"
          >
            <Select
              showSearch
              optionFilterProp="value"
              mode="tags"
              maxCount={1}
              placeholder="选择或输入维度"
              options={GROUP_SUGGESTIONS.map((g) => ({ value: g, label: g }))}
            />
          </Form.Item>
          <Form.Item name="name" label="标签名称" rules={[{ required: true, message: '请输入标签名称' }]}>
            <Input placeholder="如：门诊改造 / 指示牌 / 定稿" maxLength={50} />
          </Form.Item>
          <Form.Item name="color" label="标签颜色" extra="十六进制色值，如 #2F9E64；留空为默认色">
            <Input placeholder="#2F9E64" maxLength={20} />
          </Form.Item>
        </Form>
      </Modal>
    </Modal>
  );
};

export default TagManagerModal;
