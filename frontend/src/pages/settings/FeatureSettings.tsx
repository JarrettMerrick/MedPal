// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 功能开关页（系统设置 → 功能开关）。
 *
 * 控制**单位级**的功能启停，与「角色管理」中的功能级权限点（feature.*）构成两层控制：
 *   1) 功能开关：整个单位是否启用该功能（本页）；
 *   2) feature.* 权限点：该角色是否可访问该功能（角色管理）。
 * 两者都通过才放行；功能内部的具体操作仍由原有细粒度权限（message.send / signage.create 等）控制。
 *
 * 关闭某一功能后：左侧菜单对应入口隐藏、顶部消息铃铛（站内信）隐藏、相关接口返回 403。
 * 数据不会被删除，重新开启即可继续使用。
 *
 * 功能清单由后端 `FEATURE_META` 下发，新增功能开关时前端无需改动。
 */
import React, { useEffect, useState } from 'react';
import { App, Alert, Card, Space, Switch, Tag, Typography, theme } from 'antd';
import { ControlOutlined, FileTextOutlined, MessageOutlined, TagsOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import { useFeatures } from '../../contexts/FeaturesContext';
import { getFeatureSettings, type FeatureSettingItem } from '../../api/features';
import { updateSystemConfig } from '../../api/system-config';
import { hasPermission, PERM_SYSTEM_CONFIG } from '../../utils/permissions';
import { getErrorMessage } from '../../utils/format';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text } = Typography;
const { useToken } = theme;

/** 功能图标（按功能标识取，未登记时回退为通用图标） */
const FEATURE_ICONS: Record<string, React.ReactNode> = {
  messages: <MessageOutlined />,
  signage: <TagsOutlined />,
  // [新增 2026-09-14] 制度牌（制度管理）
  regulation: <FileTextOutlined />,
};

const FeatureSettings: React.FC = () => {
  const { user } = useAuth();
  const features = useFeatures();
  const { message } = App.useApp();
  const { token } = useToken();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<FeatureSettingItem[]>([]);
  // [调整 2026-09-14] 角色级门禁已合并为单一权限点，由后端顶层下发（用于统一提示，不逐卡片重复展示）
  const [permName, setPermName] = useState('feature.access');
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const canEdit = hasPermission(user, PERM_SYSTEM_CONFIG);

  const load = async () => {
    setLoading(true);
    try {
      const r = await getFeatureSettings();
      setItems(r.features);
      setPermName(r.permission || 'feature.access');
    } catch (err) {
      message.error(getErrorMessage(err, '加载失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 切换并保存：保存后刷新全局功能开关，使菜单与入口立即跟随，无需刷新页面 */
  const toggle = async (item: FeatureSettingItem, next: boolean) => {
    setSavingKey(item.key);
    try {
      await updateSystemConfig(item.config_key, next ? '1' : '0');
      setItems((prev) => prev.map((it) => (it.key === item.key ? { ...it, enabled: next } : it)));
      await features.refresh();
      message.success(`已${next ? '开启' : '关闭'}「${item.label}」`);
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <PageContainer>
      <PageHeader title="功能开关" />

      <div style={{ marginBottom: token.marginMD }}>
        <Text type="secondary">
          控制本单位的整体功能启停。关闭后对应菜单入口隐藏、相关接口拒绝访问；数据不会删除，重新开启即可继续使用。
        </Text>
        <Tag color={canEdit ? 'green' : 'default'} style={{ marginLeft: token.marginXS }}>
          {canEdit ? '可编辑' : '只读'}
        </Tag>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: token.marginMD }}
        message="本页是「单位级」开关，与「角色管理」中的功能权限是两层控制"
        description={
          <>
            功能开关决定<Text strong>整个单位</Text>是否启用某个模块；
            「角色管理 → 权限配置 → 功能开关」中的 <Text code>{permName}</Text> 权限则决定
            <Text strong>该角色</Text>能否访问这些模块（所有功能开关共用此一个权限点）。
            两者都通过，对应角色才能看到入口；功能内部的具体操作（如群发站内信、新增标识、编辑制度）
            仍由原有细粒度权限控制。
          </>
        }
      />

      <Space direction="vertical" size={token.marginMD} style={{ width: '100%' }}>
        {items.map((item) => (
          <Card
            key={item.key}
            loading={loading}
            title={
              <Space>
                {FEATURE_ICONS[item.key] || <ControlOutlined />}
                {item.label}
              </Space>
            }
            extra={
              <Switch
                checked={item.enabled}
                checkedChildren="已开启"
                unCheckedChildren="已关闭"
                loading={savingKey === item.key}
                disabled={!canEdit}
                onChange={(next) => toggle(item, next)}
              />
            }
          >
            <Text type="secondary" style={{ display: 'block', marginBottom: token.marginXS }}>
              影响范围：{item.applies_to}
            </Text>
            <Text>{item.description}</Text>
            {/* [调整 2026-09-14] 原「对应权限点」逐卡片重复展示已移除：
                所有功能开关共用同一个权限点，统一在页面顶部说明中提示即可 */}
          </Card>
        ))}
        {!loading && items.length === 0 && (
          <Card>
            <Text type="secondary">暂无可配置的功能开关</Text>
          </Card>
        )}
      </Space>
    </PageContainer>
  );
};

export default FeatureSettings;
