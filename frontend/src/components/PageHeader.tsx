// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 页面统一头部（v1.1.0 布局系统）。
 * 统一所有页面的主标题层级、返回按钮、右侧操作区与底部间距：
 * - 主标题固定 level={4}（18px），margin: 0
 * - 传入 onBack 时显示「返回」文本按钮（与标题间距 12px）
 * - extra 为右侧操作区（按钮组等），自动换行适配窄屏
 * - 底部间距固定 24px（与卡片/搜索区对齐）
 *
 * 使用方式：
 *   <PageHeader title="员工介绍" onBack={() => navigate(-1)} extra={<Button>新增</Button>} />
 */

import React from 'react';
import { Button, Flex, Space, Typography } from 'antd';
import { LeftOutlined } from '@ant-design/icons';
import { LAYOUT } from '../theme/tokens';

const { Text, Title } = Typography;

interface PageHeaderProps {
  /** 页面主标题 */
  title: string;
  /** 返回回调；传入则显示返回按钮 */
  onBack?: () => void;
  /** 右侧操作区（按钮组等） */
  extra?: React.ReactNode;
  /** 辅助说明文字（可选，显示在标题下方） */
  description?: React.ReactNode;
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, onBack, extra, description }) => {
  return (
    <Flex
      justify="space-between"
      align="center"
      wrap="wrap"
      gap={LAYOUT.HEADER.gap}
      style={{ marginBottom: LAYOUT.HEADER.marginBottom }}
    >
      <Space size={LAYOUT.HEADER.gap} align="center">
        {onBack && (
          <Button type="text" icon={<LeftOutlined />} onClick={onBack}>
            返回
          </Button>
        )}
        <Flex vertical gap={2}>
          <Title level={4} style={{ margin: 0 }}>{title}</Title>
          {description && <Text type="secondary" style={{ fontSize: 12 }}>{description}</Text>}
        </Flex>
      </Space>
      {extra && <Space>{extra}</Space>}
    </Flex>
  );
};

export default PageHeader;
