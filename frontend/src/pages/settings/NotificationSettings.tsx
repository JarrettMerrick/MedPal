// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 通知设置页（系统设置 → 通知设置）。
 *
 * [新增 2026-09-15]
 * ==================
 * 按**业务事件**配置系统站内信：
 *   1) 事件级开关——是否发送该通知；
 *   2) 文案模板——标题（纯文本）/ 正文（支持简单 HTML），支持 {变量} 占位；
 *   3) 收件人范围——沿用业务内置默认，或自定义规则（角色 / 科室 / 权限 / 工号 / 操作者）；
 *   4) 干跑预览与测试发送——保存前确认文案与收件人，避免误配。
 *
 * 默认行为一致性：事件清单与默认文案由后端注册表下发，管理员只保存「与默认不同」
 * 的部分；未配置的事件与改造前的通知行为逐字一致。因此本页无需前端登记事件：
 * 后端新增事件后，本页自动出现对应配置项。
 *
 * 权限：独立权限点 feature.notification（角色管理 →「系统设置」分类下的「通知设置」项），
 * 路由守卫 / 菜单入口 / 页面按钮 / 后端接口四处口径一致；存量角色由启动初始化
 * 一次性回填，升级后访问范围不缩水。
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, App, Button, Card, Checkbox, Drawer, Empty, Form, Input, Modal,
  Radio, Select, Space, Switch, Tag, Tooltip, Typography, theme,
} from 'antd';
import {
  BellOutlined, DeleteOutlined, PlusOutlined, SettingOutlined,
} from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
// [调整 2026-09-15] 页面门禁改用独立权限点 feature.notification（角色管理「系统设置」分类）
import { hasPermission, PERM_FEATURE_NOTIFICATION } from '../../utils/permissions';
import { getErrorMessage } from '../../utils/format';
import { formatDateTime } from '../../utils/time';
import useMediaQuery from '../../hooks/useMediaQuery';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import RichTextContent from '../../components/RichTextContent';
import {
  getNotificationSettings, getRecipientOptions,
  saveNotificationRule, resetNotificationRule,
  previewNotificationRule, sendTestNotification,
  type NotificationEventItem, type NotificationPreviewResult,
  type NotificationRulePayload, type RecipientOptions,
  type RecipientRuleItem, type RecipientRuleType, type RecipientRules,
} from '../../api/notification-settings';

const { Text, Paragraph } = Typography;
const { useToken } = theme;

/** 收件人规则的取值来源（后端 value_kind → 候选项） */
type ValueKind = 'roles' | 'departments' | 'permissions' | 'users';

/** 编辑抽屉的表单结构 */
interface RuleFormItem {
  type?: string;
  value?: string[];
  scope?: string | null;
}

interface RuleFormValues {
  enabled: boolean;
  title_template?: string;
  content_template?: string;
  recipient_mode?: string;
  recipient_rules?: {
    include?: RuleFormItem[];
    exclude_actor?: boolean;
  };
}

/** 把表单草稿归一化为后端 payload 结构的规则 */
const normalizeRules = (rules?: RuleFormValues['recipient_rules']): RecipientRules => ({
  include: (rules?.include || []).map((r) => {
    const item: RecipientRuleItem = { type: r.type || '' };
    if (r.value && r.value.length > 0) item.value = r.value;
    if (r.scope) item.scope = r.scope;
    return item;
  }),
  exclude_actor: rules?.exclude_actor ?? true,
});

const NotificationSettings: React.FC = () => {
  const { user } = useAuth();
  const { message, modal } = App.useApp();
  const { token } = useToken();
  const isMobile = useMediaQuery('(max-width: 768px)');

  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<NotificationEventItem[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [ruleTypes, setRuleTypes] = useState<RecipientRuleType[]>([]);
  const [limits, setLimits] = useState({ title: 200, content: 2000 });
  const [options, setOptions] = useState<RecipientOptions>({ roles: [], departments: [], permissions: [] });
  /** 卡片快捷开关保存中的事件编码 */
  const [savingCode, setSavingCode] = useState<string | null>(null);

  // ---- 编辑抽屉 ----
  const [editing, setEditing] = useState<NotificationEventItem | null>(null);
  const [form] = Form.useForm<RuleFormValues>();
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [preview, setPreview] = useState<NotificationPreviewResult | null>(null);
  /** 变量点击插入的目标：最近聚焦的字段与其原生 DOM（用于在光标处插入） */
  const lastFieldRef = useRef<'title_template' | 'content_template'>('content_template');
  const lastElRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);

  const canEdit = hasPermission(user, PERM_FEATURE_NOTIFICATION);

  // ==================== 数据加载 ====================

  const load = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await getNotificationSettings();
      setEvents(data.events || []);
      setModules(data.modules || []);
      setRuleTypes(data.rule_types || []);
      setLimits(data.limits || { title: 200, content: 2000 });
    } catch (err) {
      message.error(getErrorMessage(err, '加载失败'));
    } finally {
      if (!silent) setLoading(false);
    }
    // 候选项失败不阻塞页面（自定义规则仍可手工填写工号）
    try {
      setOptions(await getRecipientOptions());
    } catch {
      /* 忽略：仅影响自定义规则的下拉候选项 */
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 按模块分组（顺序取自后端 MODULE_ORDER，未登记的模块追加在后） */
  const grouped = useMemo(() => {
    const map = new Map<string, NotificationEventItem[]>();
    events.forEach((e) => {
      const key = e.module || '其他';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(e);
    });
    const ordered: Array<[string, NotificationEventItem[]]> = [];
    modules.forEach((m) => {
      const list = map.get(m);
      if (list && list.length > 0) {
        ordered.push([m, list]);
        map.delete(m);
      }
    });
    map.forEach((list, key) => ordered.push([key, list]));
    return ordered;
  }, [events, modules]);

  const ruleTypeMap = useMemo(
    () => new Map(ruleTypes.map((r) => [r.type, r])),
    [ruleTypes],
  );

  const valueOptions: Record<ValueKind, Array<{ value: string; label: string }>> = {
    roles: options.roles,
    departments: options.departments,
    permissions: options.permissions.map((p) => ({ value: p.value, label: p.label })),
    users: [],
  };

  // ==================== 卡片快捷开关 ====================

  /**
   * 卡片开关：只改 enabled，其余字段按「保留既有自定义 / 未自定义则继续继承默认」送回，
   * 避免一次开关操作把管理员的自定义文案或收件人规则覆盖掉。
   */
  const toggleEnabled = async (item: NotificationEventItem, next: boolean) => {
    if (item.recipient_mode === 'custom' && !item.recipient_rules) {
      message.warning('该事件的自定义收件人规则缺失，请先点「配置」重新设置后再开启');
      return;
    }
    setSavingCode(item.code);
    try {
      await saveNotificationRule(item.code, {
        enabled: next,
        title_template: item.is_custom_title ? item.title_template : '',
        content_template: item.is_custom_content ? item.content_template : '',
        recipient_mode: item.recipient_mode || 'default',
        recipient_rules: item.is_custom_recipients ? item.recipient_rules : null,
      });
      setEvents((prev) => prev.map((e) => (e.code === item.code ? { ...e, enabled: next } : e)));
      message.success(`已${next ? '开启' : '关闭'}「${item.label}」`);
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    } finally {
      setSavingCode(null);
    }
  };

  // ==================== 编辑抽屉 ====================

  const openEdit = (item: NotificationEventItem) => {
    setEditing(item);
  };

  const closeEdit = () => {
    setEditing(null);
    setPreview(null);
  };

  /** 抽屉内表单初始值（同时用于「恢复默认」后的重建） */
  const buildInitialValues = (item: NotificationEventItem): RuleFormValues => ({
    enabled: item.enabled,
    title_template: item.title_template || item.default_title,
    content_template: item.content_template || item.default_content,
    recipient_mode: item.recipient_mode === 'custom' ? 'custom' : 'default',
    recipient_rules: {
      include: (item.recipient_rules?.include || []).map((r) => ({
        type: r.type,
        value: r.value || undefined,
        scope: r.scope || undefined,
      })),
      exclude_actor: item.recipient_rules?.exclude_actor ?? true,
    },
  });

  /** 变量插入：优先插入到最近聚焦输入框的光标处，退化时追加到末尾 */
  const insertVariable = (name: string) => {
    const field = lastFieldRef.current;
    const current = (form.getFieldValue(field) as string) || '';
    const snippet = `{${name}}`;
    const el = lastElRef.current;

    if (el && el.isConnected && typeof el.selectionStart === 'number') {
      const start = el.selectionStart ?? current.length;
      const end = el.selectionEnd ?? start;
      const next = current.slice(0, start) + snippet + current.slice(end);
      form.setFieldValue(field, next);
      const pos = start + snippet.length;
      requestAnimationFrame(() => {
        el.focus();
        try {
          el.setSelectionRange(pos, pos);
        } catch {
          /* 忽略：部分浏览器在重新聚焦前不允许设置选区 */
        }
      });
      return;
    }
    form.setFieldValue(field, current + snippet);
  };

  const fillDefaultTemplates = () => {
    if (!editing) return;
    form.setFieldsValue({
      title_template: editing.default_title,
      content_template: editing.default_content,
    });
  };

  /** 保存：与默认文案一致（或清空）时送空串，让该字段继续继承注册表默认 */
  const handleSave = async () => {
    if (!editing) return;
    let values: RuleFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return; // 校验失败已由表单提示
    }

    const mode = values.recipient_mode === 'custom' ? 'custom' : 'default';
    const rules = normalizeRules(values.recipient_rules);
    if (mode === 'custom' && rules.include.length === 0) {
      message.warning('自定义收件人规则至少需要一条，请添加后再保存');
      return;
    }

    const titleTpl = (values.title_template || '').trim();
    const contentTpl = (values.content_template || '').trim();
    const payload: NotificationRulePayload = {
      enabled: values.enabled,
      title_template: titleTpl && titleTpl !== editing.default_title.trim() ? values.title_template : '',
      content_template: contentTpl && contentTpl !== editing.default_content.trim() ? values.content_template : '',
      recipient_mode: mode,
      recipient_rules: mode === 'custom' ? rules : null,
    };

    setSaving(true);
    try {
      await saveNotificationRule(editing.code, payload);
      message.success('已保存');
      closeEdit();
      await load(true);
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    } finally {
      setSaving(false);
    }
  };

  /** 恢复默认：删除该事件的全部覆盖（文案与收件人规则） */
  const handleReset = () => {
    if (!editing) return;
    const target = editing;
    modal.confirm({
      title: '恢复默认配置',
      content: `将删除「${target.label}」的全部自定义（开关 / 文案 / 收件人规则），回到系统默认行为。`,
      okText: '恢复默认',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await resetNotificationRule(target.code);
          message.success('已恢复默认配置');
          closeEdit();
          await load(true);
        } catch (err) {
          message.error(getErrorMessage(err, '恢复默认失败'));
        }
      },
    });
  };

  /** 预览：按当前表单草稿渲染，不发送、不落库 */
  const handlePreview = async () => {
    if (!editing) return;
    const values = form.getFieldsValue(true) as RuleFormValues;
    const titleTpl = (values.title_template || '').trim();
    const contentTpl = (values.content_template || '').trim();
    const mode = values.recipient_mode === 'custom' ? 'custom' : 'default';

    setPreviewing(true);
    try {
      const result = await previewNotificationRule(editing.code, {
        // 清空 = 恢复默认：空模板时不传草稿，改用默认文案渲染，预览才不会误导
        title_template: titleTpl ? values.title_template : editing.default_title,
        content_template: contentTpl ? values.content_template : editing.default_content,
        recipient_mode: mode,
        recipient_rules: mode === 'custom' ? normalizeRules(values.recipient_rules) : null,
      });
      setPreview(result);
    } catch (err) {
      message.error(getErrorMessage(err, '预览失败'));
    } finally {
      setPreviewing(false);
    }
  };

  /** 测试发送：向本人发送一封站内信（按**已保存**的配置渲染，忽略事件开关） */
  const handleTest = async () => {
    if (!editing) return;
    setTesting(true);
    try {
      const result = await sendTestNotification(editing.code);
      message.success(`测试站内信已发送（${result.title}），请到「站内信」查看`);
    } catch (err) {
      message.error(getErrorMessage(err, '发送失败'));
    } finally {
      setTesting(false);
    }
  };

  // ==================== 渲染 ====================

  return (
    <PageContainer maxWidth={960}>
      <PageHeader
        title="通知设置"
        description="按业务事件配置系统站内信的开关、文案与收件人范围"
      />

      <div style={{ marginBottom: token.marginMD }}>
        <Text type="secondary">
          只展示需要发送系统站内信的事件。未配置的事件按系统默认行为执行；保存后立即生效，无需重启。
        </Text>
        <Tag color={canEdit ? 'green' : 'default'} style={{ marginLeft: token.marginXS }}>
          {canEdit ? '可编辑' : '只读'}
        </Tag>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: token.marginMD }}
        message="文案支持 {变量} 占位；修改后建议先「预览」或「发送测试」确认效果"
        description={
          <>
            正文允许简单 HTML（如 <Text code>{'<br/>'}</Text> 换行）；变量取值会做安全转义。
            「发送测试」按<Text strong>已保存</Text>的配置向你本人发送一封测试站内信（不受事件开关限制），
            保存前后建议配合使用。
          </>
        }
      />

      {loading ? (
        <Card loading />
      ) : events.length === 0 ? (
        <Card>
          <Empty description="暂无可配置的通知事件" />
        </Card>
      ) : (
        grouped.map(([moduleName, list]) => (
          <div key={moduleName} style={{ marginBottom: token.marginLG }}>
            <Text strong style={{ display: 'block', marginBottom: token.marginSM }}>
              {moduleName}
            </Text>
            <Space direction="vertical" size={token.marginSM} style={{ width: '100%' }}>
              {list.map((item) => (
                <Card
                  key={item.code}
                  size="small"
                  title={
                    <Space size={8} wrap>
                      <BellOutlined style={{ color: token.colorPrimary }} />
                      <span>{item.label}</span>
                      {!item.enabled && <Tag>已关闭</Tag>}
                      {item.customized && <Tag color="blue">已自定义</Tag>}
                    </Space>
                  }
                  extra={
                    <Switch
                      size="small"
                      checked={item.enabled}
                      loading={savingCode === item.code}
                      disabled={!canEdit}
                      onChange={(next) => toggleEnabled(item, next)}
                    />
                  }
                >
                  <Paragraph type="secondary" style={{ marginBottom: 4, fontSize: 13 }}>
                    {item.description}
                  </Paragraph>
                  <Text style={{ fontSize: 13 }}>
                    收件人：
                    {item.recipient_mode === 'custom' && item.recipient_rules
                      ? `自定义规则（${item.recipient_rules.include.length} 条）`
                      : item.default_recipient_hint}
                  </Text>
                  <div style={{ marginTop: token.marginXS }}>
                    <Button
                      size="small"
                      icon={<SettingOutlined />}
                      disabled={!canEdit}
                      onClick={() => openEdit(item)}
                    >
                      配置
                    </Button>
                    {item.updated_at && (
                      <Text type="secondary" style={{ marginLeft: token.marginXS, fontSize: 12 }}>
                        最近更新：{item.updated_by || '-'} · {formatDateTime(item.updated_at)}
                      </Text>
                    )}
                  </div>
                </Card>
              ))}
            </Space>
          </div>
        ))
      )}

      {/* ==================== 编辑抽屉 ==================== */}
      <Drawer
        open={!!editing}
        onClose={closeEdit}
        width={isMobile ? '100%' : 760}
        destroyOnHidden
        title={
          editing && (
            <Space direction="vertical" size={0}>
              <Text strong>{editing.label}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{editing.description}</Text>
            </Space>
          )
        }
        footer={
          <Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }} wrap>
            <Space wrap>
              <Button onClick={handlePreview} loading={previewing}>预览效果</Button>
              <Tooltip title="按已保存的配置向你本人发送一封测试站内信">
                <Button onClick={handleTest} loading={testing}>发送测试</Button>
              </Tooltip>
              <Button danger onClick={handleReset}>恢复默认</Button>
            </Space>
            <Space>
              <Button onClick={closeEdit}>取消</Button>
              <Button type="primary" onClick={handleSave} loading={saving}>保存</Button>
            </Space>
          </Space>
        }
      >
        {editing && (
          <Form
            key={editing.code}
            form={form}
            layout="vertical"
            initialValues={buildInitialValues(editing)}
          >
            <Form.Item label="发送此通知" name="enabled" valuePropName="checked" style={{ marginBottom: token.marginMD }}>
              <Switch checkedChildren="开启" unCheckedChildren="关闭" disabled={!canEdit} />
            </Form.Item>

            <Form.Item
              label="标题模板（纯文本）"
              name="title_template"
              style={{ marginBottom: token.marginSM }}
            >
              <Input
                maxLength={limits.title}
                showCount
                placeholder={editing.default_title}
                disabled={!canEdit}
                onFocus={(e) => {
                  lastFieldRef.current = 'title_template';
                  lastElRef.current = e.target;
                }}
              />
            </Form.Item>

            <Form.Item
              label="正文模板（支持简单 HTML）"
              name="content_template"
              style={{ marginBottom: token.marginSM }}
            >
              <Input.TextArea
                maxLength={limits.content}
                showCount
                autoSize={{ minRows: 4, maxRows: 10 }}
                placeholder={editing.default_content}
                disabled={!canEdit}
                onFocus={(e) => {
                  lastFieldRef.current = 'content_template';
                  lastElRef.current = e.target;
                }}
              />
            </Form.Item>

            <div style={{ marginBottom: token.marginMD }}>
              <Space size={[4, 4]} wrap>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  可用变量（点击插入到最近聚焦的输入框）：
                </Text>
                {editing.variables.map((v) => (
                  <Tooltip key={v.name} title={v.desc}>
                    <Tag
                      color="processing"
                      style={{ cursor: 'pointer', margin: 0 }}
                      onClick={() => insertVariable(v.name)}
                    >
                      {`{${v.name}}`}
                    </Tag>
                  </Tooltip>
                ))}
                <Button type="link" size="small" style={{ padding: 0 }} onClick={fillDefaultTemplates}>
                  填入默认文案
                </Button>
              </Space>
            </div>

            <Form.Item label="收件人范围" name="recipient_mode" style={{ marginBottom: token.marginSM }}>
              <Radio.Group optionType="button" buttonStyle="solid" disabled={!canEdit}>
                <Radio.Button value="default">使用默认</Radio.Button>
                <Radio.Button value="custom">自定义规则</Radio.Button>
              </Radio.Group>
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) => prev.recipient_mode !== cur.recipient_mode}
            >
              {({ getFieldValue }) =>
                getFieldValue('recipient_mode') === 'custom' ? (
                  <div style={{ marginBottom: token.marginMD }}>
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: token.marginSM }}
                      message="多条规则取并集：任一条件命中的启用账号都会收到通知"
                    />
                    <Form.List name={['recipient_rules', 'include']}>
                      {(fields, { add, remove }) => (
                        <>
                          {fields.map((field) => (
                            <Form.Item
                              key={field.key}
                              noStyle
                              shouldUpdate={(prev, cur) =>
                                prev.recipient_rules?.include?.[field.name]?.type !==
                                cur.recipient_rules?.include?.[field.name]?.type
                              }
                            >
                              {({ getFieldValue: getRowValue }) => {
                                const rtype = getRowValue([
                                  'recipient_rules', 'include', field.name, 'type',
                                ]) as string | undefined;
                                const meta = rtype ? ruleTypeMap.get(rtype) : undefined;
                                const kind = (meta?.value_kind || '') as ValueKind;
                                return (
                                  <div
                                    style={{
                                      display: 'flex', gap: token.marginXS,
                                      alignItems: 'flex-start', flexWrap: 'wrap',
                                      marginBottom: token.marginXS,
                                    }}
                                  >
                                    <Form.Item
                                      name={[field.name, 'type']}
                                      noStyle
                                      rules={[{ required: true, message: '请选择规则类型' }]}
                                    >
                                      <Select
                                        style={{ width: 170 }}
                                        placeholder="规则类型"
                                        disabled={!canEdit}
                                        options={ruleTypes.map((r) => ({ value: r.type, label: r.label }))}
                                        onChange={() => {
                                          // 切换类型后清空取值与范围，避免残留上一类型的配置
                                          form.setFieldValue(['recipient_rules', 'include', field.name, 'value'], undefined);
                                          form.setFieldValue(['recipient_rules', 'include', field.name, 'scope'], undefined);
                                        }}
                                      />
                                    </Form.Item>

                                    {meta?.needs_value && (
                                      <Form.Item
                                        name={[field.name, 'value']}
                                        noStyle
                                        rules={[{ required: true, message: '请选择取值' }]}
                                      >
                                        <Select
                                          style={{ flex: 1, minWidth: 220 }}
                                          mode={kind === 'users' ? 'tags' : 'multiple'}
                                          placeholder={
                                            kind === 'users' ? '输入工号后回车'
                                              : kind === 'permissions' ? '选择权限'
                                                : kind === 'roles' ? '选择角色' : '选择科室'
                                          }
                                          disabled={!canEdit}
                                          maxTagCount="responsive"
                                          options={valueOptions[kind] || []}
                                          notFoundContent={kind === 'users' ? '输入工号后回车添加' : undefined}
                                        />
                                      </Form.Item>
                                    )}

                                    {meta?.scope && (
                                      <Form.Item name={[field.name, 'scope']} noStyle>
                                        <Select
                                          style={{ width: 190 }}
                                          allowClear
                                          placeholder="不限科室范围"
                                          disabled={!canEdit}
                                          options={[
                                            { value: 'event_department', label: '仅限本事件相关科室' },
                                          ]}
                                        />
                                      </Form.Item>
                                    )}

                                    <Button
                                      type="text"
                                      danger
                                      icon={<DeleteOutlined />}
                                      aria-label="删除该规则"
                                      disabled={!canEdit}
                                      onClick={() => remove(field.name)}
                                    />
                                  </div>
                                );
                              }}
                            </Form.Item>
                          ))}
                          <Button
                            type="dashed"
                            block
                            icon={<PlusOutlined />}
                            disabled={!canEdit}
                            onClick={() => add({ type: 'super_admins' })}
                          >
                            添加收件人规则
                          </Button>
                        </>
                      )}
                    </Form.List>

                    <Form.Item
                      name={['recipient_rules', 'exclude_actor']}
                      valuePropName="checked"
                      style={{ marginTop: token.marginSM, marginBottom: 0 }}
                    >
                      <Checkbox disabled={!canEdit}>不给操作者本人发送（操作者命中其他规则时同样排除）</Checkbox>
                    </Form.Item>
                  </div>
                ) : (
                  <Alert
                    type="success"
                    showIcon
                    style={{ marginBottom: token.marginMD }}
                    message={`默认收件人：${editing.default_recipient_hint}`}
                  />
                )
              }
            </Form.Item>
          </Form>
        )}
      </Drawer>

      {/* ==================== 预览结果 ==================== */}
      <Modal
        open={!!preview}
        onCancel={() => setPreview(null)}
        title="效果预览（不会真实发送）"
        width={620}
        footer={<Button onClick={() => setPreview(null)}>关闭</Button>}
      >
        {preview && (
          <div>
            {preview.error && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: token.marginSM }}
                message="收件人规则解析失败"
                description={preview.error}
              />
            )}
            <div style={{ marginBottom: token.marginSM }}>
              <Text type="secondary" style={{ fontSize: 12 }}>标题</Text>
              <div>
                <Text strong>{preview.title || '（空标题）'}</Text>
              </div>
            </div>
            <div style={{ marginBottom: token.marginSM }}>
              <Text type="secondary" style={{ fontSize: 12 }}>正文</Text>
              <div
                style={{
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: token.borderRadiusSM,
                  padding: token.paddingSM,
                  background: token.colorFillQuaternary,
                }}
              >
                {preview.content
                  ? <RichTextContent html={preview.content} />
                  : <Text type="secondary">（无正文）</Text>}
              </div>
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                收件人（按示例数据解析，实际发送以业务数据为准）
              </Text>
              <div style={{ marginTop: token.marginXS }}>
                <Text>共 {preview.recipients.total} 人</Text>
                {preview.recipients.preview.length > 0 && (
                  <div style={{ marginTop: token.marginXS, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {preview.recipients.preview.map((r) => (
                      <Tag key={r.employee_id} style={{ margin: 0 }}>
                        {r.name}（{r.employee_id}{r.department ? ` · ${r.department}` : ''}）
                      </Tag>
                    ))}
                    {preview.recipients.total > preview.recipients.preview.length && <Tag style={{ margin: 0 }}>…</Tag>}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </Modal>
    </PageContainer>
  );
};

export default NotificationSettings;
