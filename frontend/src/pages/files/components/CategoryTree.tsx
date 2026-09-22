// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 文件库左侧分类栏。
 *
 * [调整 2026-09-17] 需求：文件管理中的分类**沿用「标识设置 → 标识分类」**，
 * 且**不提供分类的增删改入口**——分类维护统一在标识分类设置页完成。
 * 因此本组件由原「可编辑的分类树」改为**只读分类列表**：
 *   - 虚拟节点：全部文件 / 标准设计文件 / 未分类 / 回收站（固定，不可编辑）
 *   - 分类列表：标识分类（扁平结构，无层级），点击即按该分类筛选文件
 *   - 区块标题旁提供「维护」入口（仅在拥有 signage.category 权限时展示），
 *     跳转至「标识设置 → 标识分类」页面
 *
 * 说明：标识分类本身无父子层级，故不再使用树形控件；
 * 已禁用的分类仍会展示（历史文件可能仍归属其中），以弱化样式区分。
 */
import React from 'react';
import { Typography } from 'antd';
import {
  DeleteOutlined as TrashIcon, FolderOpenOutlined, InboxOutlined, SettingOutlined,
  StarOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';

import type { FileCategoryItem } from '../../../api/designFiles';

const { Text } = Typography;

export type CategorySelection =
  | { kind: 'all' }
  | { kind: 'standard' }
  | { kind: 'uncategorized' }
  | { kind: 'trash' }
  | { kind: 'category'; id: number };

export const selectionKey = (selection: CategorySelection): string => {
  switch (selection.kind) {
    case 'all': return 'all';
    case 'standard': return 'standard';
    case 'uncategorized': return 'uncategorized';
    case 'trash': return 'trash';
    default: return `cat-${selection.id}`;
  }
};

interface CategoryTreeProps {
  categories: FileCategoryItem[];
  selection: CategorySelection;
  onSelect: (selection: CategorySelection) => void;
  summary?: { total: number; standard: number; uncategorized: number; trashed: number } | null;
  /** 是否展示「维护」入口（需 signage.category 权限；无权限时不出现，避免点击后 403） */
  canManageCategory?: boolean;
}

const CategoryTree: React.FC<CategoryTreeProps> = ({
  categories, selection, onSelect, summary, canManageCategory,
}) => {
  return (
    <div className="file-category-tree">
      <div className="file-category-tree__virtual">
        <div
          className={`file-category-virtual-item${selection.kind === 'all' ? ' is-active' : ''}`}
          onClick={() => onSelect({ kind: 'all' })}
        >
          <InboxOutlined /> <span>全部文件</span>
          <Text type="secondary">{summary?.total ?? 0}</Text>
        </div>
        <div
          className={`file-category-virtual-item${selection.kind === 'standard' ? ' is-active' : ''}`}
          onClick={() => onSelect({ kind: 'standard' })}
        >
          <StarOutlined style={{ color: 'var(--warn)' }} /> <span>标准设计文件</span>
          <Text type="secondary">{summary?.standard ?? 0}</Text>
        </div>
        <div
          className={`file-category-virtual-item${selection.kind === 'uncategorized' ? ' is-active' : ''}`}
          onClick={() => onSelect({ kind: 'uncategorized' })}
        >
          <FolderOpenOutlined /> <span>未分类</span>
          <Text type="secondary">{summary?.uncategorized ?? 0}</Text>
        </div>
        <div
          className={`file-category-virtual-item${selection.kind === 'trash' ? ' is-active' : ''}`}
          onClick={() => onSelect({ kind: 'trash' })}
        >
          <TrashIcon /> <span>回收站</span>
          <Text type="secondary">{summary?.trashed ?? 0}</Text>
        </div>
      </div>

      <div className="file-category-tree__header">
        <span>分类（标识分类）</span>
        {/* [调整 2026-09-17] 分类维护统一在标识分类设置页：此处仅提供跳转入口，无增删改 */}
        {canManageCategory && (
          <Link to="/signage-categories" className="file-category-tree__manage">
            <SettingOutlined /> 维护
          </Link>
        )}
      </div>

      {categories.length === 0 ? (
        <div className="file-category-tree__empty">
          暂无标识分类
          {canManageCategory
            ? '，请前往「标识设置 → 标识分类」新建'
            : '，请联系管理员在「标识设置 → 标识分类」中维护'}
        </div>
      ) : (
        <div className="file-category-list">
          {categories.map((category) => {
            const active = selection.kind === 'category' && selection.id === category.id;
            return (
              <div
                key={category.id}
                className={`file-category-item${active ? ' is-active' : ''}${
                  category.is_active ? '' : ' is-inactive'
                }`}
                onClick={() => onSelect({ kind: 'category', id: category.id })}
                title={category.description || category.name}
              >
                <FolderOpenOutlined className="file-category-item__icon" />
                <span className="file-category-item__name">{category.name}</span>
                {category.code && (
                  <span className="file-category-item__code">{category.code}</span>
                )}
                {!category.is_active && (
                  <span className="file-category-item__badge">已禁用</span>
                )}
                <Text type="secondary" className="file-category-item__count">
                  {category.file_count || 0}
                </Text>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default CategoryTree;
