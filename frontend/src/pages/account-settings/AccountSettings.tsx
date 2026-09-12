// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 账号设置页：新建账号默认口令规则 + 登录页注册开关。
 *
 * - 默认口令模板支持 `{工号}` 占位符（如 `MedPal@{工号}`）；留空则使用内置默认 `MedPal@2026`。
 *   该规则作用于「后台新建用户 / 批量建号 / 导入人员建号」三处；
 *   登录页自助注册的账号使用其注册时填写的密码，不受本规则限制。
 * - 注册开关开启后，登录页出现「注册账号」入口，申请需经审核通过才能登录。
 * - 无 system.config 权限时整页只读。
 */
import React, { useEffect, useState } from 'react';
import { App, Alert, Button, Card, Col, Form, Input, Row, Space, Switch, Tag, Typography, theme } from 'antd';
import { KeyOutlined, UserAddOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import { getAccountSettings } from '../../api/account-settings';
import { updateSystemConfig } from '../../api/system-config';
import { hasPermission, PERM_SYSTEM_CONFIG } from '../../utils/permissions';
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

  const canEdit = hasPermission(user, PERM_SYSTEM_CONFIG);
  // 实时预览：随输入变化，便于管理员确认模板效果
  const template = Form.useWatch('default_password_template', form) ?? '';
  const effectiveTemplate = (template || '').trim() || FALLBACK_TEMPLATE;
  const preview = effectiveTemplate.replace('{工号}', PREVIEW_EMPLOYEE_ID);

  const load = async () => {
    setLoading(true);
    try {
      const data = await getAccountSettings();
      form.setFieldsValue({
        default_password_template: data.default_password_template,
        registration_enabled: data.registration_enabled,
      });
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

  return (
    <PageContainer>
      <PageHeader title="账号设置" />

      <div style={{ marginBottom: token.marginMD }}>
        <Text type="secondary">
          维护新建账号的默认密码规则与登录页注册开关。
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
      </Row>
    </PageContainer>
  );
};

export default AccountSettings;
