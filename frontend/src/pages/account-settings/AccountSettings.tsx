// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 账号设置页：新建账号默认口令规则 + 登录页注册开关 + 批量重置密码（全员 / 按科室定向）。
 *
 * - 默认口令模板支持 `{工号}` 占位符（如 `MedPal@{工号}`）；留空则使用内置默认 `MedPal@2026`。
 *   该规则作用于「后台新建用户 / 批量建号 / 导入人员建号 / 批量重置密码」四处；
 *   登录页自助注册的账号使用其注册时填写的密码，不受本规则限制。
 * - 注册开关开启后，登录页出现「注册账号」入口，申请需经审核通过才能登录。
 * - [新增 2026-09-14] 批量重置密码：除超级管理员外，账号改用上述规则生成的新口令，
 *   需二次输入操作者本人的登录密码确认；重置后相关账号立即下线并强制改密。
 * - [调整 2026-09-14] 支持单选 / 多选科室定向重置：
 *   不选科室 = 全员（旧行为）；选中后仅重置所选科室的账号，影响人数随选择实时预估。
 * - 无 system.config 权限时整页只读；批量重置还需额外具备 user.reset_password 权限。
 */
import React, { useEffect, useMemo, useState } from 'react';
import { App, Alert, Button, Card, Col, Form, Input, Modal, Progress, Row, Select, Space, Switch, Tag, Typography, theme } from 'antd';
import { KeyOutlined, SafetyCertificateOutlined, UserAddOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
// [调整 2026-09-15] 批量重置改为后台任务 + 进度轮询：新增 getResetTask / getLatestResetTask
import { getAccountSettings, resetAllPasswords, getResetTask, getLatestResetTask } from '../../api/account-settings';
import type { DepartmentResetOption, ResetTask } from '../../api/account-settings';
import { updateSystemConfig } from '../../api/system-config';
import { hasPermission, PERM_SYSTEM_CONFIG, PERM_USER_RESET_PWD } from '../../utils/permissions';
import { getErrorMessage } from '../../utils/format';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text } = Typography;
const { useToken } = theme;

/** 口令模板为空时的内置默认（与后端 DEFAULT_PASSWORD_TEMPLATE_FALLBACK 一致） */
const FALLBACK_TEMPLATE = 'MedPal@2026';
/** 预览用的示例工号 */
const PREVIEW_EMPLOYEE_ID = '905182';

interface AccountFormValues {
  default_password_template: string;
  registration_enabled: boolean;
}

const AccountSettings: React.FC = () => {
  const { user } = useAuth();
  const { message } = App.useApp();
  const { token } = useToken();
  const [form] = Form.useForm<AccountFormValues>();
  const [loading, setLoading] = useState(true);
  const [savingPwd, setSavingPwd] = useState(false);
  const [savingReg, setSavingReg] = useState(false);

  // [新增 2026-09-14] 批量重置密码
  // [调整 2026-09-15] 改为后台任务 + 进度条：弹窗按阶段切换（确认 → 进行中 → 结果）
  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetPhase, setResetPhase] = useState<'confirm' | 'running' | 'done'>('confirm');
  /** 当前重置任务：进行中用于进度展示，完成后用于结果展示 */
  const [resetTask, setResetTask] = useState<ResetTask | null>(null);
  const [resetPwdForm] = Form.useForm<{ password: string }>();
  /** 影响范围：可重置账号数 / 被跳过的超级管理员数（由接口下发） */
  const [resetCount, setResetCount] = useState(0);
  const [superAdminCount, setSuperAdminCount] = useState(0);
  /** [新增 2026-09-14] 按科室定向重置：各科室可重置账号数 + 未分配科室的账号数 */
  const [deptOptions, setDeptOptions] = useState<DepartmentResetOption[]>([]);
  const [unassignedCount, setUnassignedCount] = useState(0);
  /** 已选科室（空数组 = 不限科室，即全员） */
  const [selectedDepts, setSelectedDepts] = useState<string[]>([]);

  const canEdit = hasPermission(user, PERM_SYSTEM_CONFIG);
  // 批量改密属高危操作：比「保存配置」额外要求 user.reset_password 权限
  const canReset = canEdit && hasPermission(user, PERM_USER_RESET_PWD);
  // 实时预览：随输入变化，便于管理员确认模板效果
  const template = Form.useWatch('default_password_template', form) ?? '';
  const effectiveTemplate = (template || '').trim() || FALLBACK_TEMPLATE;
  const preview = effectiveTemplate.replace('{工号}', PREVIEW_EMPLOYEE_ID);
  // 模板不含 {工号} 时，所有被重置的账号会拿到**同一个**口令，界面须重点警示
  const isUniformTemplate = !effectiveTemplate.includes('{工号}');

  // [新增 2026-09-14] 未选科室 = 不限科室（全员，旧行为）；选中则只重置所选科室
  const isAllScope = selectedDepts.length === 0;
  /**
   * 本次预估影响人数：本地按 `GET /api/account-settings` 下发的科室人数求和，
   * 不再请求接口——勾选/取消是高频交互，本地计算可避免连点时数字滞后。
   * 注意「未分配科室」的账号（unassignedCount）只在全员重置时计入，
   * 与后端 _department_scope_filter 的口径保持一致。
   */
  const scopeCount = useMemo(() => {
    if (isAllScope) return resetCount;
    return deptOptions
      .filter((d) => selectedDepts.includes(d.name))
      .reduce((sum, d) => sum + d.resettable_user_count, 0);
  }, [isAllScope, resetCount, deptOptions, selectedDepts]);

  /** 科室下拉项：标签带上该科室人数，便于按影响面挑选 */
  const deptSelectOptions = useMemo(
    () =>
      deptOptions.map((d) => ({
        value: d.name,
        label: `${d.name}（${d.resettable_user_count}）`,
      })),
    [deptOptions],
  );

  /** 范围描述（用于提示文案与确认弹窗）：科室过多时只列前 5 个，避免撑爆弹窗 */
  const scopeText = isAllScope
    ? '全部科室（除超级管理员外全员）'
    : `${selectedDepts.length} 个科室：${selectedDepts.slice(0, 5).join('、')}${
        selectedDepts.length > 5 ? ` 等 ${selectedDepts.length} 个` : ''
      }`;

  const load = async () => {
    setLoading(true);
    try {
      const data = await getAccountSettings();
      form.setFieldsValue({
        default_password_template: data.default_password_template,
        registration_enabled: data.registration_enabled,
      });
      setResetCount(data.resettable_user_count ?? 0);
      setSuperAdminCount(data.super_admin_count ?? 0);
      const depts = data.departments ?? [];
      setDeptOptions(depts);
      setUnassignedCount(data.unassigned_user_count ?? 0);
      // 科室被删除后重新加载：剔除已不存在的选项，避免提交时被后端 400 拦下
      setSelectedDepts((prev) => prev.filter((name) => depts.some((d) => d.name === name)));
    } catch (err) {
      console.error('[account-settings] 加载失败:', err);
      message.error(getErrorMessage(err, '加载失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // [新增 2026-09-15] 页面加载时恢复「进行中」的重置任务：
  // 刷新页面 / 重新进入后直接切回进度条，避免用户以为"没反应"而重复提交
  useEffect(() => {
    (async () => {
      try {
        const t = await getLatestResetTask();
        if (t && t.status === 'running') {
          setResetTask(t);
          setResetPhase('running');
          setResetOpen(true);
        }
      } catch {
        /* 静默：恢复失败不影响主流程 */
      }
    })();
  }, []);

  // [新增 2026-09-15] 进行中任务按 1s 轮询**实际进度**；完成 / 失败后切到结果阶段
  const activeTaskId = resetTask?.task_id;
  const resetRunning = resetOpen && resetPhase === 'running';
  useEffect(() => {
    if (!resetRunning || !activeTaskId) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const t = await getResetTask(activeTaskId);
        if (cancelled) return;
        setResetTask(t);
        if (t.status !== 'running') {
          setResetPhase('done');
          // 操作者本人不在范围内时刷新页面数据（科室人数等）
          if (!t.self_included) load();
        }
      } catch {
        /* 单次失败忽略，下一轮自动重试 */
      }
    }, 1000);
    return () => { cancelled = true; clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetRunning, activeTaskId]);

  /** 保存默认口令模板 */
  const saveTemplate = async () => {
    setSavingPwd(true);
    try {
      await updateSystemConfig('default_password_template', (template || '').trim());
      message.success('默认密码规则已保存');
      await load();
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    } finally {
      setSavingPwd(false);
    }
  };

  /** 切换并保存注册开关 */
  const toggleRegistration = async (next: boolean) => {
    setSavingReg(true);
    try {
      await updateSystemConfig('registration_enabled', next ? '1' : '0');
      form.setFieldValue('registration_enabled', next);
      message.success(next ? '已开启登录页注册入口' : '已关闭登录页注册入口');
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    } finally {
      setSavingReg(false);
    }
  };

  /**
   * [新增 2026-09-14] 批量重置密码：不限科室（全员）或按所选科室定向。
   *
   * 后端要求二次输入操作者本人的登录密码；密码错误返回 400 且不做任何改动。
   * 科室范围直接取当前勾选值（空数组 = 不限科室），由后端再做一次「科室是否仍存在」的校验。
   */
  const handleResetPasswords = async () => {
    let values: { password: string };
    try {
      values = await resetPwdForm.validateFields();
    } catch {
      return; // 校验未通过：保持弹窗打开，错误由表单自身提示
    }
    setResetting(true);
    try {
      // [调整 2026-09-15] 异步任务模式：POST 只创建任务并立即返回，
      // 弹窗随即切到「进行中」阶段，由轮询 effect 按**实际进度**更新
      const task = await resetAllPasswords(values.password, selectedDepts);
      resetPwdForm.resetFields();
      setResetTask(task);
      setResetPhase(task.status === 'running' ? 'running' : 'done');
      // 操作者本人也在重置范围内时，其 token 已失效，再调接口只会拿到 401，故跳过刷新
      if (!task.self_included) {
        await load();
      }
    } catch (err) {
      message.error(getErrorMessage(err, '重置失败'));
      // 409（已有进行中任务）：切换到该任务的进度展示，而不是停留在确认框反复点击
      try {
        const t = await getLatestResetTask();
        if (t && t.status === 'running') {
          setResetTask(t);
          setResetPhase('running');
        }
      } catch {
        /* 静默：恢复进度失败时仍停留在确认框 */
      }
    } finally {
      setResetting(false);
    }
  };

  /** 关闭重置弹窗并复位到「确认」阶段（进行中的任务会在后台继续执行） */
  const closeResetModal = () => {
    setResetOpen(false);
    setResetPhase('confirm');
    setResetTask(null);
    resetPwdForm.resetFields();
  };

  return (
    <PageContainer>
      <PageHeader title="账号设置" />

      <div style={{ marginBottom: token.marginMD }}>
        <Text type="secondary">
          维护新建账号的默认密码规则、登录页注册开关，以及按科室批量重置账号密码。
        </Text>
        <Tag color={canEdit ? 'green' : 'default'} style={{ marginLeft: token.marginXS }}>
          {canEdit ? '可编辑' : '只读'}
        </Tag>
      </div>

      <Row gutter={[token.marginMD, token.marginMD]}>
        {/* 新建账户默认密码 */}
        <Col xs={24} lg={12}>
          <Card title={<Space><KeyOutlined />新建账户默认密码</Space>} loading={loading} style={{ height: '100%' }}>
            <Form<AccountFormValues> form={form} layout="vertical" disabled={!canEdit}>
              <Form.Item
                label="默认密码规则（模板）"
                name="default_password_template"
                extra="支持 {工号} 占位符，例如：MedPal@{工号} → MedPal@905182；留空则使用默认 MedPal@2026"
                rules={[{ max: 50, message: '最多 50 个字符' }]}
              >
                <Input placeholder="例如：MedPal@{工号}" maxLength={50} showCount allowClear />
              </Form.Item>

              <Alert
                type="info"
                showIcon
                message={
                  <>
                    生成效果预览：
                    <Text strong copyable code>{preview}</Text>
                  </>
                }
                description="该规则用于后台新建用户、批量创建账号、导入人员建号；登录页自助注册的账号使用其注册密码，不受此规则限制。"
                style={{ marginBottom: token.marginSM }}
              />

              <Button type="primary" loading={savingPwd} onClick={saveTemplate} disabled={!canEdit}>
                保存规则
              </Button>
            </Form>
          </Card>
        </Col>

        {/* 登录页注册开关 */}
        <Col xs={24} lg={12}>
          <Card title={<Space><UserAddOutlined />登录页注册</Space>} loading={loading} style={{ height: '100%' }}>
            <Form<AccountFormValues> form={form} layout="vertical" disabled={!canEdit}>
              <Form.Item
                label="开启注册入口"
                name="registration_enabled"
                valuePropName="checked"
                extra="开启后，登录页显示「注册账号」入口；申请人需填写工号、密码、姓名、工种、所属科室，经科室管理员审核通过后方可登录。"
              >
                <Switch
                  checkedChildren="已开启"
                  unCheckedChildren="已关闭"
                  loading={savingReg}
                  disabled={!canEdit}
                  onChange={toggleRegistration}
                />
              </Form.Item>
            </Form>
            <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
              审核入口位于左侧菜单「业务 → 信息审核」，审核权限与科室范围一致：科室管理员仅能审核本科室申请。
            </Text>
          </Card>
        </Col>

        {/* [新增 2026-09-14] 批量重置密码：高危操作，独占整行；[调整] 支持按科室单选/多选定向 */}
        <Col xs={24}>
          <Card
            title={<Space><SafetyCertificateOutlined />批量重置密码</Space>}
            loading={loading}
            style={{ borderColor: token.colorWarningBorder }}
          >
            <Form layout="vertical" disabled={!canReset} style={{ maxWidth: 560 }}>
              <Form.Item
                label="重置范围（科室）"
                extra="可单选或多选科室；留空表示不限科室，将对除超级管理员外的全部账号执行重置"
                style={{ marginBottom: token.marginMD }}
              >
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="不选 = 全部科室（全员）"
                  value={selectedDepts}
                  onChange={setSelectedDepts}
                  options={deptSelectOptions}
                  maxTagCount="responsive"
                  notFoundContent="暂无科室"
                />
              </Form.Item>
            </Form>

            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: token.marginMD }}
              message={
                isAllScope
                  ? '将把「除超级管理员外」的全部账号密码重置为默认密码规则生成的新口令'
                  : `将把所选 ${selectedDepts.length} 个科室的账号密码重置为默认密码规则生成的新口令`
              }
              description={
                <div style={{ lineHeight: 1.9 }}>
                  <div>
                    · 重置范围：<Text strong>{scopeCount}</Text> 个账号（{scopeText}）
                    {/*
                      超管数量只在「不限科室」时回显：后端在定向重置时只统计所选科室内的超管，
                      而前端拿到的是全量值，直接展示会与实际跳过数不符，故定向时只做定性说明。
                    */}
                    {isAllScope
                      ? `，超级管理员 ${superAdminCount} 个将被跳过、不受影响`
                      : '，超级管理员不在重置范围内'}
                  </div>
                  {unassignedCount > 0 && (
                    <div>
                      {isAllScope
                        ? `· 其中 ${unassignedCount} 个账号未分配科室，仅在全员重置时会被覆盖`
                        : `· 另有 ${unassignedCount} 个账号未分配科室，不在本次范围内（如需一并重置，请清空上面的科室选择）`}
                    </div>
                  )}
                  <div>
                    · 新密码规则：<Text code copyable>{effectiveTemplate}</Text>
                    ，与上方「新建账户默认密码」同一模板（保存新规则后再重置即可生效）
                  </div>
                  <div>· 重置后相关账号立即下线，需重新登录，且首次登录须修改密码</div>
                  {isUniformTemplate && (
                    <div style={{ color: token.colorError }}>
                      · 注意：当前规则不含「工号」占位符，范围内账号将得到<Text strong>同一个口令</Text>
                      <Text strong copyable code>{preview}</Text>
                      ，泄露一个即等同于泄露全部，请尽快通知使用者自行改密
                    </div>
                  )}
                </div>
              }
            />
            <Space wrap>
              <Button
                danger
                type="primary"
                icon={<SafetyCertificateOutlined />}
                disabled={!canReset}
                onClick={() => {
                  resetPwdForm.resetFields();
                  setResetOpen(true);
                }}
              >
                {isAllScope ? '重置全员密码' : '重置所选科室密码'}
              </Button>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                {canReset
                  ? isAllScope
                    ? '此操作不可撤销；当前未选科室 = 重置全员，点击后还需输入你的登录密码二次确认'
                    : '此操作不可撤销，点击后还需输入你的登录密码二次确认'
                  : '需同时具备「系统设置」与「重置密码」权限'}
              </Text>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* [新增 2026-09-14] 二次确认弹窗：必须重新输入操作者本人的登录密码 */}
      {/* [调整 2026-09-15] 三阶段：确认 → 进行中（实际进度条）→ 结果；进行中允许关闭（后台继续执行） */}
      <Modal
        title={
          resetPhase === 'running'
            ? '正在重置密码'
            : resetPhase === 'done'
              ? (resetTask?.status === 'failed' ? '重置失败' : (resetTask?.message || '重置完成'))
              : isAllScope
                ? '确认重置全员密码？'
                : `确认重置所选科室（${selectedDepts.length} 个）密码？`
        }
        open={resetOpen}
        onCancel={resetPhase === 'confirm' ? () => setResetOpen(false) : closeResetModal}
        onOk={resetPhase === 'confirm' ? handleResetPasswords : closeResetModal}
        okText={resetPhase === 'confirm' ? '确认重置' : '知道了'}
        cancelText="取消"
        okButtonProps={{
          danger: resetPhase === 'confirm',
          loading: resetPhase === 'confirm' && resetting,
        }}
        footer={
          resetPhase === 'running' ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: token.marginSM }}>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                任务在后台继续执行，可关闭本窗口，稍后重新进入查看进度
              </Text>
              <Button onClick={closeResetModal}>后台运行</Button>
            </div>
          ) : resetPhase === 'done' ? (
            <Button type="primary" onClick={closeResetModal}>知道了</Button>
          ) : undefined
        }
        maskClosable={resetPhase !== 'confirm'}
        width={560}
      >
        {resetPhase === 'confirm' && (
          <>
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: token.marginMD }}
              message="此操作不可撤销"
              description={
                <>
                  将把 <Text strong>{scopeCount}</Text> 个账号的密码重置为「默认密码规则」生成的新口令；
                  重置范围：{scopeText}，超级管理员不在范围内；
                  这些账号会立即下线，并须在下次登录时修改密码。
                </>
              }
            />
            <Form form={resetPwdForm} layout="vertical">
              <Form.Item
                label="当前登录密码"
                name="password"
                extra="二次确认：请输入你本人的登录密码；密码错误将不执行任何重置"
                rules={[{ required: true, message: '请输入当前登录密码以确认身份' }]}
              >
                <Input.Password
                  placeholder="请输入当前登录密码"
                  autoComplete="current-password"
                  maxLength={128}
                  onPressEnter={handleResetPasswords}
                />
              </Form.Item>
            </Form>
          </>
        )}

        {resetPhase === 'running' && resetTask && (
          <div>
            {/* [新增 2026-09-15] 实际进度：processed / total（后端分批提交，进度实时更新） */}
            <Progress
              percent={
                resetTask.total > 0
                  ? Math.min(100, Math.floor((resetTask.processed / resetTask.total) * 100))
                  : 100
              }
              status="active"
            />
            <div style={{ marginTop: token.marginSM, fontSize: token.fontSizeSM, lineHeight: 1.9 }}>
              <div>
                · 实际进度：<Text strong>{resetTask.processed}</Text> / {resetTask.total} 个账号已处理
              </div>
              <div>
                · 重置范围：
                {resetTask.is_all_departments
                  ? '全部科室（除超级管理员外全员）'
                  : resetTask.departments.join('、')}
              </div>
              <div>· 处理完成后本窗口会自动显示结果，请勿重复提交</div>
            </div>
          </div>
        )}

        {resetPhase === 'done' && resetTask && (
          resetTask.status === 'failed' ? (
            <Alert
              type="error"
              showIcon
              message="重置任务执行失败"
              description={resetTask.error || '未知错误，请查看系统日志后重试'}
            />
          ) : (
            <div style={{ fontSize: token.fontSizeSM, lineHeight: 1.9 }}>
              <div>
                · 重置范围：
                {resetTask.is_all_departments ? '全部科室（除超级管理员外全员）' : resetTask.departments.join('、')}
              </div>
              <div>
                · 已重置账号：<Text strong>{resetTask.total}</Text> 个
                {resetTask.inactive_count > 0 ? `（含已停用账号 ${resetTask.inactive_count} 个）` : ''}
              </div>
              <div>
                · 跳过超级管理员：<Text strong>{resetTask.super_admin_excluded}</Text> 个（不受影响）
              </div>
              {resetTask.unassigned_excluded > 0 && (
                <div>
                  · 未分配科室跳过：<Text strong>{resetTask.unassigned_excluded}</Text> 个
                  （不在所选科室范围内）
                </div>
              )}
              <div>
                · 新密码规则：<Text code copyable>{resetTask.password_rule}</Text>
              </div>
              {resetTask.is_uniform ? (
                <div style={{ color: token.colorError }}>
                  · 范围内统一新口令：<Text strong copyable code>{resetTask.uniform_password}</Text>
                  （规则不含「工号」占位符，请尽快通知使用者登录后自行改密）
                </div>
              ) : (
                <div>· 各账号新口令 = 上述规则中的「工号」替换为本人 6 位工号</div>
              )}
              <div>· 被重置的账号已全部下线，需重新登录；首次登录会强制修改密码</div>
              {resetTask.total === 0 && (
                <div style={{ color: token.colorWarning }}>
                  · 本次未改动任何账号，请确认所选科室下是否存在账号
                </div>
              )}
              {resetTask.self_included && (
                <div style={{ color: token.colorError }}>
                  · 你的账号也在重置范围内，请使用新口令重新登录
                </div>
              )}
            </div>
          )
        )}
      </Modal>
    </PageContainer>
  );
};

export default AccountSettings;
