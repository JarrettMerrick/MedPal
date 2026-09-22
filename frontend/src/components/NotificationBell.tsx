// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 站内信铃铛组件，挂载在 Layout 的 Header 中。
 *
 * [调整 2026-09-11] 「统一站内信」改造后，系统通知已并入站内信：
 * - 未读数、列表改走 `/api/messages`（与「站内信」页面同一数据源）；
 * - 点击某条 → 标记已读并跳转站内信页面定位该条（原先点击仅关闭弹窗、无跳转）；
 * - 底部新增「查看全部站内信」入口。
 *
 * [调整 2026-09-15] 未读数改由 MessageUnreadContext 统一提供（左侧「站内信」菜单红点、
 * 本铃铛、站内信页共用同一数据源与同一轮询），本组件不再自行轮询。
 *
 * 负责：
 * 1. 展示未读数量（数据源见上）
 * 2. 点击展开最近 5 条站内信
 * 3. 单条已读 / 全部已读
 * 4. 跳转站内信页面
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Popover, Badge, Button, List, Typography, Divider, theme } from 'antd';
import { BellOutlined, RightOutlined } from '@ant-design/icons';
import { listInbox, markRead, markAllRead } from '../api/messages';
import type { MessageItem } from '../api/messages';
// [新增 2026-09-15] 未读数改用全局 Provider（与左侧「站内信」菜单红点、站内信页同源）：
// 三处数字保证一致，且全站只保留一处轮询（轮询/聚焦刷新/退出清零见 MessageUnreadContext）
import { useMessageUnread } from '../contexts/MessageUnreadContext';
import { timeAgo as formatTimeAgo } from '../utils/time';

const { Text } = Typography;
const { useToken } = theme;

/** 弹层内展示的条数 */
const PAGE_SIZE = 5;

const NotificationBell: React.FC = () => {
  const { token } = useToken();
  const navigate = useNavigate();
  // 未读数来自 MessageUnreadContext（本组件不再自行轮询）
  const { unread, setUnread } = useMessageUnread();
  const [items, setItems] = useState<MessageItem[]>([]);
  const [open, setOpen] = useState(false);

  const fetchRecent = async () => {
    try {
      const data = await listInbox({ page: 1, page_size: PAGE_SIZE });
      setItems(data.items);
      setUnread(data.unread);
    } catch {
      // ignore
    }
  };

  // 打开弹窗时加载列表
  useEffect(() => {
    if (open) fetchRecent();
  }, [open]);

  /** 标记单条已读 */
  const handleMarkRead = async (id: number) => {
    try {
      await markRead(id);
      setItems((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
      setUnread((u) => Math.max(0, u - 1));
    } catch {
      // ignore
    }
  };

  /** 全部标记已读 */
  const handleMarkAllRead = async () => {
    try {
      await markAllRead();
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnread(0);
    } catch {
      // ignore
    }
  };

  /** 点击某条：标记已读并跳转站内信页面 */
  const handleItemClick = (n: MessageItem) => {
    if (!n.is_read) handleMarkRead(n.id);
    setOpen(false);
    navigate(`/messages?id=${n.id}`);
  };

  const popoverContent = (
    <div style={{ width: 340 }}>
      {/* 标题栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: token.paddingXS,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          marginBottom: token.marginXS,
        }}
      >
        <Text strong>站内信</Text>
        {unread > 0 && (
          <Button type="link" size="small" onClick={handleMarkAllRead}>
            全部标为已读
          </Button>
        )}
      </div>

      {/* 列表 */}
      {items.length === 0 ? (
        <div style={{ textAlign: 'center', padding: `${token.paddingLG}px 0` }}>
          <Text type="secondary">暂无站内信</Text>
        </div>
      ) : (
        <List
          dataSource={items}
          renderItem={(n) => (
            <div
              onClick={() => handleItemClick(n)}
              style={{
                padding: `${token.paddingXS}px ${token.paddingSM}px`,
                cursor: 'pointer',
                borderRadius: token.borderRadius,
                backgroundColor: !n.is_read ? token.colorPrimaryBg : 'transparent',
                transition: 'background-color 0.2s',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.backgroundColor = token.colorFillQuaternary; }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLDivElement).style.backgroundColor = !n.is_read ? token.colorPrimaryBg : 'transparent';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: token.marginXS }}>
                {!n.is_read && (
                  <Badge status="processing" style={{ marginTop: token.marginXS, flexShrink: 0 }} />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Text
                    strong={!n.is_read}
                    style={{ fontSize: token.fontSize, display: 'block' }}
                    ellipsis
                  >
                    {n.title}
                  </Text>
                  {n.content && (
                    <Text
                      type="secondary"
                      style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXXS }}
                      ellipsis
                    >
                      {n.content.replace(/<[^>]*>/g, '')}
                    </Text>
                  )}
                  <Text type="secondary" style={{ fontSize: token.fontSizeSM, marginTop: token.marginXS, display: 'block' }}>
                    {formatTimeAgo(n.created_at)}
                  </Text>
                </div>
              </div>
            </div>
          )}
          style={{ maxHeight: 320, overflowY: 'auto' }}
        />
      )}

      <Divider style={{ margin: `${token.marginXS}px 0` }} />
      <div style={{ textAlign: 'center' }}>
        <Button
          type="link"
          size="small"
          onClick={() => { setOpen(false); navigate('/messages'); }}
        >
          查看全部站内信 <RightOutlined style={{ fontSize: 12 }} />
        </Button>
      </div>
    </div>
  );

  return (
    <Popover
      content={popoverContent}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      arrow={false}
    >
      <Badge count={unread} overflowCount={99} size="small" offset={[-2, 2]}>
        <Button
          type="text"
          icon={<BellOutlined />}
          aria-label="站内信"
          style={{ color: token.colorTextSecondary }}
        />
      </Badge>
    </Popover>
  );
};

export default NotificationBell;
