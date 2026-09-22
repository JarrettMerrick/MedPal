// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file in the project root for details.

/**
 * 标准设计文件选择器。
 *
 * [新增 2026-09-17] 需求：文件被标记为「标准设计文件」后，上传标识设计文件时
 * 可通过搜索选择该标准设计文件（引用共享，不复制物理文件）。
 *
 * 交互：关键词搜索（文件名）+ 分类筛选 + 缩略图列表；
 * 选中即回填标识编辑页的设计文件（路径 + 文件库引用 ID）。
 */
import React, { useCallback, useEffect, useState } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import { App, Empty, Input, List, Modal, Select, Space, Spin, Tag, Typography } from 'antd';
import { SearchOutlined, StarFilled } from '@ant-design/icons';

import { getStandardFileOptions, listFileCategories } from '../../../api/designFiles';
import type { FileCategoryItem, StandardFileOption } from '../../../api/designFiles';
import { fileExtLabel } from '../../../utils/fileUtils';

const { Text } = Typography;

interface StandardFilePickerProps {
  open: boolean;
  onClose: () => void;
  /** 选中标准设计文件（返回文件库记录，含 stored_path 与 id） */
  onSelect: (file: StandardFileOption) => void;
  /**
   * [新增 2026-09-17] 当前标识的分类名。
   * 传入时**限定只能选择同分类的标准设计文件**（跨类别引用会造成数据混乱）；
   * 不传则保持原行为（可自由按分类浏览），向后兼容其它调用方。
   */
  categoryName?: string;
}

const StandardFilePicker: React.FC<StandardFilePickerProps> = ({
  open, onClose, onSelect, categoryName,
}) => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [categoryId, setCategoryId] = useState<number | undefined>(undefined);
  const [items, setItems] = useState<StandardFileOption[]>([]);
  const [categories, setCategories] = useState<FileCategoryItem[]>([]);
  // [新增 2026-09-17] 标识表单场景：限定为当前标识分类（服务端按分类名过滤）
  const limitToCategory = !!categoryName;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getStandardFileOptions({
        keyword: keyword.trim() || undefined,
        category_id: limitToCategory ? undefined : categoryId,
        category_name: limitToCategory ? categoryName : undefined,
      });
      setItems(result.items);
    } catch {
      message.error('获取标准设计文件失败');
    } finally {
      setLoading(false);
    }
  }, [keyword, categoryId, limitToCategory, categoryName]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // 分类下拉的数据源：仅在不限定分类时需要（限定场景不展示下拉，省一次请求）
  useEffect(() => {
    if (!open || limitToCategory) return;
    listFileCategories()
      .then((res) => setCategories(res.items))
      .catch(() => setCategories([]));
  }, [open, limitToCategory]);

  // [调整 2026-09-17] 分类沿用标识分类（扁平结构，无层级），直接映射
  const categoryOptions = React.useMemo(
    () => categories.map((category) => ({
      value: category.id,
      label: category.is_active ? category.name : `${category.name}（已禁用）`,
    })),
    [categories],
  );

  return (
    <Modal
      title="从标准库选择设计文件"
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          allowClear
          placeholder="搜索标准设计文件名"
          prefix={<SearchOutlined />}
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onPressEnter={() => load()}
        />
        {/* [新增 2026-09-17] 标识表单场景：锁定为当前标识分类，不提供跨分类下拉 */}
        {limitToCategory ? (
          <Tag color="blue" style={{ marginInlineEnd: 0 }}>
            仅限「{categoryName}」分类
          </Tag>
        ) : (
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="按分类筛选"
            style={{ width: 200 }}
            value={categoryId}
            onChange={setCategoryId}
            options={categoryOptions}
          />
        )}
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {items.length} 个标准文件
        </Text>
      </Space>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={limitToCategory
            ? `暂无「${categoryName}」分类的标准设计文件；请先在「文件管理」中把该分类的文件标记为标准（星标）`
            : '暂无标准设计文件；可在「文件管理」中将常用文件标记为标准（星标）'}
        />
      ) : (
        <List
          size="small"
          style={{ maxHeight: 420, overflowY: 'auto' }}
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() => { onSelect(item); onClose(); }}
              extra={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {item.ref_count > 0 ? `已被 ${item.ref_count} 条标识引用` : '尚未被引用'}
                </Text>
              }
            >
              <List.Item.Meta
                avatar={
                  item.preview_type === 'image' && item.thumbnail_path ? (
                    <div className="file-thumb">
                      <img src={`/uploads/${item.thumbnail_path}`} alt={item.name} loading="lazy" />
                    </div>
                  ) : (
                    <div className="file-thumb file-thumb--ext"><span>{fileExtLabel(item.file_ext)}</span></div>
                  )
                }
                title={(
                  <Space size={6} wrap>
                    <StarFilled style={{ color: 'var(--warn)' }} />
                    <span>{item.name}</span>
                    <Tag style={{ marginInlineEnd: 0 }}>{fileExtLabel(item.file_ext)}</Tag>
                    {item.category_name && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{item.category_name}</Tag>}
                  </Space>
                )}
                description={
                  item.tags.length ? (
                    <Space size={4} wrap>
                      {item.tags.map((tag) => (
                        <Tag key={tag.id} color={tag.color || 'default'} style={{ marginInlineEnd: 0 }}>
                          {tag.name}
                        </Tag>
                      ))}
                    </Space>
                  ) : <Text type="secondary">未设置标签</Text>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
};

export default StandardFilePicker;
