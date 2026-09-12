// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 科室树形多选组件，用于用户管理中配置科室权限范围。
 * 数据结构：三级分类（临床科室/护理病区/行政科室）→ 科室列表。
 * 支持分类级全选/取消、半选状态展示、科室级单选。
 * 
 * 改造说明（v1.1.0）：
 * - [改进] 手写 checkbox 递归树 → Ant Design Tree 组件（checkable 模式）
 * - [改进] 全选/半选逻辑 → Tree 内置 checkStrictly={false} 自动处理
 * - [改进] 原生 checkbox → Tree 统一勾选交互
 * - 分组排序和选中计算逻辑保留不变
 */

import React, { useMemo, useCallback } from 'react';
import { Tree, Empty } from 'antd';
import type { DataNode } from 'antd/es/tree';

// ==================== 接口定义 ====================

interface DeptItem {
  id: number;
  name: string;
  category: string;
}

interface DepartmentTreeSelectProps {
  departments: DeptItem[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}

// ==================== 常量 ====================

/** 科室分类中文标签映射 */
const CATEGORY_LABELS: Record<string, string> = {
  '临床专科': '临床科室',
  '护理病区': '护理病区',
  '行政科室': '行政科室',
};

/** 分类固定排序 */
const CATEGORY_ORDER = ['临床专科', '护理病区', '行政科室'];

// ==================== 组件 ====================

const DepartmentTreeSelect: React.FC<DepartmentTreeSelectProps> = ({ departments, selectedIds, onChange }) => {
  // 按分类分组并排序
  const grouped = useMemo(() => {
    const map: Record<string, DeptItem[]> = {};
    for (const d of departments) {
      const cat = d.category || '其他';
      if (!map[cat]) map[cat] = [];
      map[cat].push(d);
    }
    const ordered: { category: string; items: DeptItem[] }[] = [];
    for (const cat of CATEGORY_ORDER) {
      if (map[cat]) {
        ordered.push({ category: cat, items: map[cat].sort((a, b) => a.name.localeCompare(b.name, 'zh')) });
      }
    }
    for (const cat of Object.keys(map).sort()) {
      if (!CATEGORY_ORDER.includes(cat)) {
        ordered.push({ category: cat, items: map[cat].sort((a, b) => a.name.localeCompare(b.name, 'zh')) });
      }
    }
    return ordered;
  }, [departments]);

  // [改进] 构建 Tree 所需的 treeData
  const treeData: DataNode[] = useMemo(() => {
    return grouped.map((group) => {
      const catLabel = CATEGORY_LABELS[group.category] || group.category;
      const checkedCount = group.items.filter((d) => selectedIds.includes(d.id)).length;
      return {
        key: `cat_${group.category}`,
        title: `${catLabel}（${checkedCount}/${group.items.length}）`,
        selectable: false,
        children: group.items.map((dept) => ({
          key: dept.id,
          title: dept.name,
        })),
      };
    });
  }, [grouped, selectedIds]);

  // [改进] 使用 Tree 的 onCheck 处理选中变化
  const handleCheck = useCallback(
    (checkedKeysValue: React.Key[] | { checked: React.Key[]; halfChecked: React.Key[] }) => {
      const checkedKeys = Array.isArray(checkedKeysValue)
        ? checkedKeysValue
        : checkedKeysValue.checked;
      // 过滤掉分类节点 key（字符串），只保留科室 ID（数字）
      const deptIds = checkedKeys
        .filter((key) => typeof key === 'number')
        .map((key) => key as number);
      onChange(deptIds);
    },
    [onChange]
  );

  // 无数据时展示空状态
  if (grouped.length === 0) {
    return <Empty description="暂无科室数据" />;
  }

  return (
    <Tree
      checkable
      defaultExpandAll
      treeData={treeData}
      checkedKeys={selectedIds}
      onCheck={handleCheck}
      style={{ maxHeight: 400, overflowY: 'auto' }}
    />
  );
};

export default DepartmentTreeSelect;
