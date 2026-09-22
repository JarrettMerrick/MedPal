// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 站内信（统一消息中心）
 *
 * [新增 2026-09-11] 功能：
 * 1. 收件箱：按「全部 / 未读 / 星标 / 归档 / 自定义标签」筛选，支持关键字搜索、
 *    批量已读、批量星标、批量归档、批量删除；
 * 2. 发件箱：查看已发送的群发/私发消息，含收件人数、已读数与逐人明细；
 * 3. 写站内信：私发（选人）或群发（全员 / 按科室 / 按角色 / 按权限 / 指定人员），
 *    发送前可预览收件人数与名单；需 message.send / message.broadcast 权限；
 * 4. 标注：星标、归档、自定义标签字典（每人一套，可增删改）。
 *
 * 数据来源：系统通知与人工消息已统一到站内信，顶栏铃铛展示的即未读站内信。
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  App, Button, Card, Col, Drawer, Empty, Form, Input, List, Modal, Pagination,
  Radio, Row, Select, Space, Table, Tabs, Tag, Tooltip, Typography, theme,
} from 'antd';
import {
  DeleteOutlined, InboxOutlined, ReloadOutlined, SendOutlined,
  StarFilled, StarOutlined, TagsOutlined, PushpinOutlined, EyeOutlined,
} from '@ant-design/icons';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import RichTextEditor from '../../components/RichTextEditor';
import RichTextContent from '../../components/RichTextContent';
import { useAuth } from '../../contexts/AuthContext';
// [新增 2026-09-15] 未读数全局 Provider：左侧菜单红点 / 顶栏铃铛 / 本页未读计数共用同一数据源
import { useMessageUnread } from '../../contexts/MessageUnreadContext';
import { hasPermission, PERM_MESSAGE_BROADCAST, PERM_MESSAGE_SEND } from '../../utils/permissions';
import { getErrorMessage } from '../../utils/format';
import { formatDateTime } from '../../utils/time';
import { getUsers } from '../../api/users';
import { getAllDepartments } from '../../api/departments';
import { getAllRoles, getPermissionsByCategory } from '../../api/roles';
import * as msgApi from '../../api/messages';
import type {
  BroadcastTarget, InboxBox, MessageItem, MessageTagItem, SentItem, SentDetail,
} from '../../api/messages';

const { Text, Paragraph } = Typography;
const { useToken } = theme;

const PAGE_SIZE = 10;

/** 消息类型 → 展示标签 */
const TYPE_META: Record<string, { label: string; color: string }> = {
  system: { label: '系统通知', color: 'blue' },
  broadcast: { label: '群发', color: 'purple' },
  direct: { label: '私发', color: 'green' },
};

/** 群发目标类型选项 */
const TARGET_OPTIONS: { value: BroadcastTarget; label: string }[] = [
  { value: 'all', label: '全员' },
  { value: 'departments', label: '按科室' },
  { value: 'roles', label: '按角色' },
  { value: 'permissions', label: '按权限' },
  { value: 'users', label: '指定人员' },
];

interface DirUser { employee_id: string; name: string; department: string | null }
interface DirRole { name: string; display_name: string }
interface DirPerm { name: string; display_name: string }
interface DirDept { id: number; name: string }

const Messages: React.FC = () => {
  const { message: msg, modal } = App.useApp();
  const { token } = useToken();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const canSend = hasPermission(user, PERM_MESSAGE_SEND);
  const canBroadcast = hasPermission(user, PERM_MESSAGE_BROADCAST);

  const [tab, setTab] = useState<string>('inbox');
  // ---- 收件箱 ----
  const [box, setBox] = useState<InboxBox>('all');
  const [tagFilter, setTagFilter] = useState<number | null>(null);
  const [keyword, setKeyword] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<MessageItem[]>([]);
  const [total, setTotal] = useState(0);
  // [调整 2026-09-15] 未读数改用全局 Provider（与左侧「站内信」菜单红点、顶栏铃铛同源）：
  // 本页加载收件箱 / 标记已读时写入的数字会同步反映到菜单红点与铃铛，避免三处口径不一致
  const { unread, setUnread } = useMessageUnread();
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [tags, setTags] = useState<MessageTagItem[]>([]);
  // ---- 详情 ----
  const [detail, setDetail] = useState<MessageItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  // ---- 发件箱 ----
  const [sentItems, setSentItems] = useState<SentItem[]>([]);
  const [sentTotal, setSentTotal] = useState(0);
  const [sentPage, setSentPage] = useState(1);
  const [sentLoading, setSentLoading] = useState(false);
  const [sentDetail, setSentDetail] = useState<SentDetail | null>(null);
  // ---- 写站内信 ----
  const [composeType, setComposeType] = useState<'direct' | 'broadcast'>('direct');
  const [targetType, setTargetType] = useState<BroadcastTarget>('all');
  const [targetValues, setTargetValues] = useState<string[]>([]);
  const [recipients, setRecipients] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [composeLoading, setComposeLoading] = useState(false);
  const [preview, setPreview] = useState<msgApi.RecipientPreview | null>(null);
  // ---- 通讯录（选人用） ----
  const [dirUsers, setDirUsers] = useState<DirUser[]>([]);
  const [dirRoles, setDirRoles] = useState<DirRole[]>([]);
  const [dirPerms, setDirPerms] = useState<DirPerm[]>([]);
  const [dirDepts, setDirDepts] = useState<DirDept[]>([]);
  // ---- 标签管理 ----
  const [tagMgrOpen, setTagMgrOpen] = useState(false);
  const [newTagName, setNewTagName] = useState('');

  // ==================== 数据加载 ====================

  const loadTags = useCallback(async () => {
    try {
      setTags(await msgApi.listTags());
    } catch {
      /* 标签加载失败不阻塞主流程 */
    }
  }, []);

  const loadInbox = useCallback(async () => {
    setLoading(true);
    try {
      const res = await msgApi.listInbox({
        page, page_size: PAGE_SIZE, box,
        tag_id: tagFilter ?? undefined,
        keyword: keyword || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
      setUnread(res.unread);
    } catch (err) {
      msg.error(getErrorMessage(err, '加载失败'));
    } finally {
      setLoading(false);
    }
  }, [page, box, tagFilter, keyword, msg]);

  const loadSent = useCallback(async () => {
    setSentLoading(true);
    try {
      const res = await msgApi.listSent({ page: sentPage, page_size: PAGE_SIZE });
      setSentItems(res.items);
      setSentTotal(res.total);
    } catch (err) {
      msg.error(getErrorMessage(err, '加载失败'));
    } finally {
      setSentLoading(false);
    }
  }, [sentPage, msg]);

  useEffect(() => { loadInbox(); }, [loadInbox]);
  useEffect(() => { loadTags(); }, [loadTags]);
  useEffect(() => { if (tab === 'sent') loadSent(); }, [tab, loadSent]);

  // 从铃铛跳转过来时（/messages?id=xx）直接打开详情
  useEffect(() => {
    const id = Number(searchParams.get('id') || 0);
    if (id > 0) {
      msgApi.getMessageDetail(id)
        .then((m) => { setDetail(m); setDetailOpen(true); loadInbox(); })
        .catch(() => { /* 忽略：可能已被删除 */ });
      searchParams.delete('id');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams, loadInbox]);

  // 选人数据（仅发送权限需要）
  useEffect(() => {
    if (!canSend) return;
    getUsers({ page: 1, page_size: 100 }).then((r) => setDirUsers(r.items)).catch(() => {});
    getAllDepartments().then((r) => setDirDepts(r)).catch(() => {});
    getAllRoles().then((r) => setDirRoles(r)).catch(() => {});
    getPermissionsByCategory().then((cats) => {
      setDirPerms(cats.flatMap((c) => c.permissions.map((p) => ({ name: p.name, display_name: p.display_name }))));
    }).catch(() => {});
  }, [canSend]);

  // ==================== 收件箱操作 ====================

  const openDetail = async (row: MessageItem) => {
    setDetail(row);
    setDetailOpen(true);
    if (!row.is_read) {
      try {
        await msgApi.markRead(row.id);
        setItems((prev) => prev.map((i) => (i.id === row.id ? { ...i, is_read: true } : i)));
        setUnread((u) => Math.max(0, u - 1));
      } catch { /* 忽略 */ }
    }
  };

  const handleStar = async (row: MessageItem, starred: boolean) => {
    try {
      await msgApi.updateFlags({ ids: [row.id], is_starred: starred });
      setItems((prev) => prev.map((i) => (i.id === row.id ? { ...i, is_starred: starred } : i)));
      if (detail?.id === row.id) setDetail({ ...detail, is_starred: starred });
    } catch (err) {
      msg.error(getErrorMessage(err, '操作失败'));
    }
  };

  const handleArchive = async (ids: number[], archived: boolean) => {
    try {
      await msgApi.updateFlags({ ids, is_archived: archived });
      msg.success(archived ? '已归档' : '已取消归档');
      setSelectedIds([]);
      loadInbox();
    } catch (err) {
      msg.error(getErrorMessage(err, '操作失败'));
    }
  };

  const handleBatchRead = async () => {
    if (!selectedIds.length) return;
    try {
      await msgApi.markReadBatch(selectedIds);
      msg.success('已标记为已读');
      setSelectedIds([]);
      loadInbox();
    } catch (err) {
      msg.error(getErrorMessage(err, '操作失败'));
    }
  };

  const handleBatchDelete = () => {
    if (!selectedIds.length) return;
    modal.confirm({
      title: `确定删除选中的 ${selectedIds.length} 条站内信吗？`,
      content: '删除后仅从你的收件箱移除，不影响其他收件人。',
      okType: 'danger',
      onOk: async () => {
        try {
          await msgApi.bulkDelete(selectedIds);
          msg.success('已删除');
          setSelectedIds([]);
          loadInbox();
        } catch (err) {
          msg.error(getErrorMessage(err, '删除失败'));
        }
      },
    });
  };

  const handleReadAll = async () => {
    try {
      const res = await msgApi.markAllRead();
      msg.success(`已标记 ${res.count ?? 0} 条为已读`);
      loadInbox();
    } catch (err) {
      msg.error(getErrorMessage(err, '操作失败'));
    }
  };

  const handleSetTag = async (ids: number[], tagId: number | null) => {
    try {
      await msgApi.updateFlags(
        tagId === null ? { ids, clear_tag: true } : { ids, tag_id: tagId },
      );
      msg.success('已更新标签');
      setSelectedIds([]);
      loadInbox();
      loadTags();
    } catch (err) {
      msg.error(getErrorMessage(err, '操作失败'));
    }
  };

  // ==================== 标签管理 ====================

  const handleCreateTag = async () => {
    if (!newTagName.trim()) { msg.warning('请输入标签名称'); return; }
    try {
      await msgApi.createTag(newTagName.trim());
      setNewTagName('');
      loadTags();
      msg.success('已创建');
    } catch (err) {
      msg.error(getErrorMessage(err, '创建失败'));
    }
  };

  const handleDeleteTag = (tag: MessageTagItem) => {
    modal.confirm({
      title: `删除标签「${tag.name}」？`,
      content: '标签下的站内信不会被删除，只会解除标签。',
      okType: 'danger',
      onOk: async () => {
        try {
          await msgApi.deleteTag(tag.id);
          if (tagFilter === tag.id) setTagFilter(null);
          loadTags();
          loadInbox();
        } catch (err) {
          msg.error(getErrorMessage(err, '删除失败'));
        }
      },
    });
  };

  // ==================== 发送 ====================

  const handlePreview = async () => {
    try {
      const data = await msgApi.previewRecipients(targetType, targetValues);
      setPreview(data);
      if (data.total === 0) msg.warning('没有匹配到收件人');
    } catch (err) {
      msg.error(getErrorMessage(err, '预览失败'));
    }
  };

  const handleSend = async () => {
    if (!title.trim()) { msg.warning('请填写标题'); return; }
    if (composeType === 'direct' && !recipients.length) { msg.warning('请选择收件人'); return; }
    if (composeType === 'broadcast' && targetType !== 'all' && !targetValues.length) {
      msg.warning('请选择群发范围'); return;
    }
    setComposeLoading(true);
    try {
      const res = await msgApi.sendMessage(
        composeType === 'direct'
          ? { title: title.trim(), content, send_type: 'direct', recipients }
          : { title: title.trim(), content, send_type: 'broadcast', target_type: targetType, target_values: targetValues },
      );
      msg.success(res.message);
      setTitle(''); setContent(''); setRecipients([]); setTargetValues([]); setPreview(null);
      setTab('sent'); setSentPage(1);
    } catch (err) {
      msg.error(getErrorMessage(err, '发送失败'));
    } finally {
      setComposeLoading(false);
    }
  };

  // ==================== 渲染 ====================

  const userOptions = dirUsers.map((u) => ({
    value: u.employee_id,
    label: `${u.name}（${u.employee_id}${u.department ? ' · ' + u.department : ''}）`,
  }));

  /** 群发范围选择器（按 target_type 渲染不同数据源） */
  const broadcastValuePicker = () => {
    if (targetType === 'all') return <Text type="secondary">将发送给系统内全部启用账号</Text>;
    const common = { mode: 'multiple' as const, style: { width: '100%' }, placeholder: '请选择', value: targetValues, onChange: (v: string[]) => { setTargetValues(v); setPreview(null); } };
    if (targetType === 'departments') {
      return <Select {...common} options={dirDepts.map((d) => ({ value: d.name, label: d.name }))} />;
    }
    if (targetType === 'roles') {
      return <Select {...common} options={dirRoles.map((r) => ({ value: r.name, label: r.display_name }))} />;
    }
    if (targetType === 'permissions') {
      return (
        <Select
          {...common}
          showSearch
          optionFilterProp="label"
          options={dirPerms.map((p) => ({ value: p.name, label: p.display_name }))}
        />
      );
    }
    return <Select {...common} showSearch optionFilterProp="label" options={userOptions} />;
  };

  const boxOptions: { key: string; label: string; count?: number }[] = [
    { key: 'all', label: '全部' },
    { key: 'unread', label: '未读', count: unread },
    { key: 'starred', label: '星标' },
    { key: 'archived', label: '归档' },
  ];

  const inboxColumns = [
    {
      title: '标题',
      dataIndex: 'title',
      render: (_: unknown, row: MessageItem) => (
        <Space size={token.marginXXS}>
          {!row.is_read && <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 3, background: token.colorError }} />}
          {row.is_starred && <StarFilled style={{ color: token.colorWarning }} />}
          <Text strong={!row.is_read} style={{ cursor: 'pointer' }} onClick={() => openDetail(row)}>
            {row.title}
          </Text>
        </Space>
      ),
    },
    {
      title: '类型', dataIndex: 'msg_type', width: 96,
      render: (t: string) => <Tag color={TYPE_META[t]?.color}>{TYPE_META[t]?.label || t}</Tag>,
    },
    {
      title: '标签', dataIndex: 'tag_name', width: 110,
      render: (name: string | null, row: MessageItem) =>
        name ? <Tag color={row.tag_color || 'default'}>{name}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '发送人', dataIndex: 'sender_name', width: 110,
      render: (n: string | null, row: MessageItem) => n || (row.msg_type === 'system' ? <Text type="secondary">系统</Text> : row.sender_id || '—'),
    },
    {
      title: '时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => <Text type="secondary">{formatDateTime(v)}</Text>,
    },
    {
      title: '操作', width: 160,
      render: (_: unknown, row: MessageItem) => (
        <Space size={0}>
          <Tooltip title={row.is_starred ? '取消星标' : '标星'}>
            <Button
              type="text" size="small"
              icon={row.is_starred ? <StarFilled style={{ color: token.colorWarning }} /> : <StarOutlined />}
              onClick={() => handleStar(row, !row.is_starred)}
            />
          </Tooltip>
          <Tooltip title={row.is_archived ? '取消归档' : '归档'}>
            <Button type="text" size="small" icon={<PushpinOutlined />} onClick={() => handleArchive([row.id], !row.is_archived)} />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              type="text" size="small" danger icon={<DeleteOutlined />}
              onClick={() => modal.confirm({
                title: '确定删除该条站内信吗？', okType: 'danger',
                onOk: async () => {
                  try { await msgApi.deleteMessage(row.id); loadInbox(); }
                  catch (err) { msg.error(getErrorMessage(err, '删除失败')); }
                },
              })}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const sentColumns = [
    { title: '标题', dataIndex: 'title' },
    {
      title: '类型', dataIndex: 'msg_type', width: 100,
      render: (t: string) => <Tag color={TYPE_META[t]?.color}>{TYPE_META[t]?.label || t}</Tag>,
    },
    {
      title: '送达', width: 120,
      render: (_: unknown, row: SentItem) => (
        <Text>{row.read_count}/{row.recipient_count} 已读</Text>
      ),
    },
    {
      title: '发送时间', dataIndex: 'created_at', width: 170,
      render: (v: string) => <Text type="secondary">{formatDateTime(v)}</Text>,
    },
    {
      title: '操作', width: 100,
      render: (_: unknown, row: SentItem) => (
        <Button
          type="link" size="small" icon={<EyeOutlined />}
          onClick={async () => {
            try { setSentDetail(await msgApi.getSentDetail(row.id)); }
            catch (err) { msg.error(getErrorMessage(err, '加载失败')); }
          }}
        >
          明细
        </Button>
      ),
    },
  ];

  const inboxTab = (
    <Row gutter={[token.marginMD, token.marginMD]}>
      {/* 左侧：分类 + 标签 */}
      <Col xs={24} md={6}>
        <Card
          size="small"
          title="分类"
          extra={
            <Tooltip title="管理我的标签">
              <Button type="text" size="small" icon={<TagsOutlined />} onClick={() => setTagMgrOpen(true)} />
            </Tooltip>
          }
        >
          <List
            size="small"
            dataSource={boxOptions}
            renderItem={(o) => {
              const active = !tagFilter && box === o.key;
              return (
                <List.Item
                  onClick={() => { setBox(o.key as InboxBox); setTagFilter(null); setPage(1); setSelectedIds([]); }}
                  style={{ cursor: 'pointer', paddingLeft: active ? token.paddingXS : 0, background: active ? token.colorPrimaryBg : undefined, borderRadius: token.borderRadius }}
                >
                  <Space>
                    <InboxOutlined style={{ color: active ? token.colorPrimary : token.colorTextTertiary }} />
                    <Text strong={active}>{o.label}</Text>
                    {!!o.count && <Tag color="red">{o.count}</Tag>}
                  </Space>
                </List.Item>
              );
            }}
          />
          {tags.length > 0 && (
            <>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block', margin: `${token.marginXS}px 0` }}>
                我的标签
              </Text>
              <List
                size="small"
                dataSource={tags}
                renderItem={(t) => {
                  const active = tagFilter === t.id;
                  return (
                    <List.Item
                      onClick={() => { setTagFilter(t.id); setBox('all'); setPage(1); setSelectedIds([]); }}
                      style={{ cursor: 'pointer', paddingLeft: active ? token.paddingXS : 0, background: active ? token.colorPrimaryBg : undefined, borderRadius: token.borderRadius }}
                    >
                      <Space>
                        <Tag color={t.color || 'default'} style={{ marginRight: 0 }}>{t.name}</Tag>
                        <Text type="secondary">{t.count}</Text>
                      </Space>
                    </List.Item>
                  );
                }}
              />
            </>
          )}
        </Card>
      </Col>

      {/* 右侧：列表 */}
      <Col xs={24} md={18}>
        <Card size="small">
          <Space wrap style={{ marginBottom: token.marginSM }}>
            <Input.Search
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onSearch={(v) => { setKeyword(v); setPage(1); }}
              placeholder="搜索标题或内容"
              allowClear
              style={{ width: 220 }}
            />
            <Button icon={<ReloadOutlined />} onClick={() => loadInbox()}>刷新</Button>
            {unread > 0 && <Button onClick={handleReadAll}>全部已读</Button>}
          </Space>

          {selectedIds.length > 0 && (
            <Space wrap style={{ marginBottom: token.marginSM }}>
              <Text type="secondary">已选 {selectedIds.length} 条：</Text>
              <Button size="small" onClick={handleBatchRead}>标记已读</Button>
              <Button size="small" onClick={() => handleArchive(selectedIds, true)}>归档</Button>
              <Select
                size="small" placeholder="打标签" style={{ width: 130 }} value={undefined}
                options={tags.map((t) => ({ value: t.id, label: t.name }))}
                onChange={(v) => handleSetTag(selectedIds, v ?? null)}
              />
              <Button size="small" onClick={() => handleSetTag(selectedIds, null)}>清除标签</Button>
              <Button size="small" danger icon={<DeleteOutlined />} onClick={handleBatchDelete}>删除</Button>
            </Space>
          )}

          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={items}
            columns={inboxColumns}
            pagination={false}
            locale={{ emptyText: <Empty description="暂无站内信" /> }}
            rowSelection={{ selectedRowKeys: selectedIds, onChange: (keys) => setSelectedIds(keys as number[]) }}
          />
          {total > PAGE_SIZE && (
            <Row justify="end" style={{ marginTop: token.marginSM }}>
              <Pagination
                size="small" current={page} pageSize={PAGE_SIZE} total={total}
                showTotal={(t) => `共 ${t} 条`}
                onChange={(p) => setPage(p)}
              />
            </Row>
          )}
        </Card>
      </Col>
    </Row>
  );

  const sentTab = (
    <Card size="small">
      <Space style={{ marginBottom: token.marginSM }}>
        <Button icon={<ReloadOutlined />} onClick={() => loadSent()}>刷新</Button>
        {(canSend || canBroadcast) && (
          <Button type="primary" icon={<SendOutlined />} onClick={() => setTab('compose')}>写站内信</Button>
        )}
      </Space>
      <Table
        size="small" rowKey="id" loading={sentLoading}
        dataSource={sentItems} columns={sentColumns} pagination={false}
        locale={{ emptyText: <Empty description="暂无发送记录" /> }}
      />
      {sentTotal > PAGE_SIZE && (
        <Row justify="end" style={{ marginTop: token.marginSM }}>
          <Pagination
            size="small" current={sentPage} pageSize={PAGE_SIZE} total={sentTotal}
            showTotal={(t) => `共 ${t} 条`}
            onChange={(p) => setSentPage(p)}
          />
        </Row>
      )}
    </Card>
  );

  const composeTab = (
    <Card size="small">
      <Form layout="vertical" style={{ maxWidth: 860 }}>
        <Form.Item label="发送方式">
          <Radio.Group
            value={composeType}
            onChange={(e) => { setComposeType(e.target.value); setPreview(null); }}
          >
            <Radio.Button value="direct" disabled={!canSend}>私发（指定人员）</Radio.Button>
            <Radio.Button value="broadcast" disabled={!canBroadcast}>群发（按范围）</Radio.Button>
          </Radio.Group>
        </Form.Item>

        {composeType === 'direct' ? (
          <Form.Item label="收件人" required>
            <Select
              mode="multiple" showSearch optionFilterProp="label"
              placeholder="输入姓名或工号搜索"
              value={recipients}
              onChange={setRecipients}
              options={userOptions}
              maxTagCount="responsive"
            />
          </Form.Item>
        ) : (
          <>
            <Form.Item label="群发范围" required>
              <Select
                value={targetType}
                onChange={(v) => { setTargetType(v); setTargetValues([]); setPreview(null); }}
                options={TARGET_OPTIONS}
                style={{ maxWidth: 220 }}
              />
            </Form.Item>
            <Form.Item label="范围明细">
              {broadcastValuePicker()}
            </Form.Item>
            <Form.Item>
              <Space>
                <Button onClick={handlePreview}>预览收件人</Button>
                {preview && <Text type="secondary">共 {preview.total} 人</Text>}
              </Space>
              {preview && preview.preview.length > 0 && (
                <div style={{ marginTop: token.marginXS }}>
                  {preview.preview.slice(0, 12).map((p) => (
                    <Tag key={p.employee_id}>{p.name || p.employee_id}{p.department ? ` · ${p.department}` : ''}</Tag>
                  ))}
                  {preview.total > preview.preview.length && <Text type="secondary">…等 {preview.total} 人</Text>}
                </div>
              )}
            </Form.Item>
          </>
        )}

        <Form.Item label="标题" required>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} showCount placeholder="请输入标题" />
        </Form.Item>
        <Form.Item label="正文">
          <RichTextEditor value={content} onChange={setContent} placeholder="请输入正文（支持富文本）" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" icon={<SendOutlined />} loading={composeLoading} onClick={handleSend}>
            发送
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );

  return (
    <PageContainer>
      <PageHeader title="站内信" description="系统通知与管理员消息统一在此查看；可星标、归档、打标签" />

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'inbox', label: <Space>收件箱{unread > 0 && <Tag color="red">{unread}</Tag>}</Space>, children: inboxTab },
          { key: 'sent', label: '发件箱', children: sentTab },
          ...((canSend || canBroadcast)
            ? [{ key: 'compose', label: '写站内信', children: composeTab }]
            : []),
        ]}
      />

      {/* 收件详情 */}
      <Drawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width={620}
        title={detail?.title}
        extra={detail && (
          <Space>
            <Tooltip title={detail.is_starred ? '取消星标' : '标星'}>
              <Button
                size="small"
                icon={detail.is_starred ? <StarFilled style={{ color: token.colorWarning }} /> : <StarOutlined />}
                onClick={() => handleStar(detail, !detail.is_starred)}
              />
            </Tooltip>
            <Button size="small" onClick={() => handleArchive([detail.id], !detail.is_archived)}>
              {detail.is_archived ? '取消归档' : '归档'}
            </Button>
          </Space>
        )}
      >
        {detail && (
          <>
            <Space wrap style={{ marginBottom: token.marginMD }}>
              <Tag color={TYPE_META[detail.msg_type]?.color}>{TYPE_META[detail.msg_type]?.label}</Tag>
              <Text type="secondary">
                发送人：{detail.sender_name || (detail.msg_type === 'system' ? '系统' : detail.sender_id) || '系统'}
              </Text>
              <Text type="secondary">{formatDateTime(detail.created_at)}</Text>
            </Space>
            <div style={{ marginBottom: token.marginSM }}>
              <Space>
                <Text type="secondary">标签：</Text>
                <Select
                  size="small" placeholder="选择标签" style={{ width: 160 }}
                  value={detail.tag_id ?? undefined}
                  options={tags.map((t) => ({ value: t.id, label: t.name }))}
                  onChange={(v) => handleSetTag([detail.id], v ?? null)}
                  allowClear
                />
              </Space>
            </div>
            {detail.content
              ? <RichTextContent html={detail.content} />
              : <Paragraph type="secondary">（无正文）</Paragraph>}
            {detail.related_type === 'staff' && (
              <Button
                type="link" style={{ paddingLeft: 0 }}
                onClick={() => navigate(`/staff/view/${detail.related_id ?? ''}`)}
              >
                查看相关人员
              </Button>
            )}
            {/* [新增 2026-09-11] 人员信息变更审核提醒：一键跳转到审核页并定位该条变更 */}
            {detail.related_type === 'staff_change' && (
              <Space>
                <Button
                  type="primary" size="small"
                  onClick={() => navigate(`/registration-review?tab=change&id=${detail.related_id ?? ''}`)}
                >
                  去审核
                </Button>
                <Button
                  type="link" size="small" style={{ paddingLeft: 0 }}
                  onClick={() => navigate('/registration-review?tab=change')}
                >
                  查看全部待审核
                </Button>
              </Space>
            )}
          </>
        )}
      </Drawer>

      {/* 发件明细 */}
      <Drawer
        open={!!sentDetail}
        onClose={() => setSentDetail(null)}
        width={560}
        title={sentDetail ? `发送明细 · ${sentDetail.title}` : ''}
      >
        {sentDetail && (
          <>
            <Space style={{ marginBottom: token.marginSM }}>
              <Text type="secondary">共 {sentDetail.recipient_count} 人，已读 {sentDetail.read_count} 人</Text>
            </Space>
            <List
              size="small"
              dataSource={sentDetail.recipients}
              renderItem={(r) => (
                <List.Item extra={r.is_read ? <Tag color="green">已读</Tag> : <Tag>未读</Tag>}>
                  <Space>
                    <Text>{r.name || r.employee_id}</Text>
                    <Text type="secondary">{r.employee_id}{r.department ? ` · ${r.department}` : ''}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </>
        )}
      </Drawer>

      {/* 标签管理 */}
      <Modal open={tagMgrOpen} onCancel={() => setTagMgrOpen(false)} title="我的标签" footer={null}>
        <Space style={{ marginBottom: token.marginSM, width: '100%' }}>
          <Input
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            placeholder="新标签名称（最多 30 字）"
            maxLength={30}
            onPressEnter={handleCreateTag}
            style={{ width: 240 }}
          />
          <Button type="primary" onClick={handleCreateTag}>新增</Button>
        </Space>
        <List
          size="small"
          dataSource={tags}
          locale={{ emptyText: '暂无标签' }}
          renderItem={(t) => (
            <List.Item
              actions={[
                <Button key="del" type="link" size="small" danger onClick={() => handleDeleteTag(t)}>删除</Button>,
              ]}
            >
              <Space>
                <Tag color={t.color || 'default'} style={{ marginRight: 0 }}>{t.name}</Tag>
                <Text type="secondary">{t.count} 条</Text>
              </Space>
            </List.Item>
          )}
        />
      </Modal>

    </PageContainer>
  );
};

export default Messages;
