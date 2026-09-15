// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 登录页面，系统唯一不需要登录的公开路由。
 * 支持工号+密码登录，可选"记住我"（3 天内自动登录）。
 * 登录成功后跳转至 /dashboard。
 * 
 * 改造说明（v1.1.0）：
 * - [改进] 手写白色卡片 div → Ant Design Card 组件
 * - [改进] 内联 SVG 图标 → @ant-design/icons FileTextOutlined
 * - [改进] useState 表单管理 → Ant Design Form 声明式表单
 * - [改进] 手写 input/checkbox → Input.Password / Checkbox 组件
 * - [改进] 手写按钮 → Button 组件（loading 属性）
 * - [改进] 手写 error div → Alert 组件
 * - 蓝色渐变背景保留（Tailwind 装饰，不影响功能）
 */

import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Form, Input, Button, Checkbox, Card, Alert, Typography, theme } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
// [新增 2026-09-10] 品牌信息（单位 Logo / 单位名称 / 系统名称）
import { useBranding } from '../../contexts/BrandingContext';
import { getRegistrationOptions } from '../../api/registration';
import BrandLogo from '../../components/BrandLogo'; // [调整 2026-09-10] 统一 Logo：高度固定、宽度等比

const { Title, Text } = Typography;
const { useToken } = theme;

/** 登录表单字段类型 */
interface LoginFormValues {
  employeeId: string;
  password: string;
  rememberMe: boolean;
}

const Login: React.FC = () => {
  const [form] = Form.useForm<LoginFormValues>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const branding = useBranding(); // [新增 2026-09-10] 品牌信息
  const navigate = useNavigate();
  const { token } = useToken();
  // [新增 2026-09-10] 注册开关：开启时在登录卡片底部展示注册入口
  const [regEnabled, setRegEnabled] = useState(false);

  useEffect(() => {
    getRegistrationOptions()
      .then((opt) => setRegEnabled(!!opt.enabled))
      .catch((err) => {
        console.error('[login] 获取注册开关失败:', err);
      });
  }, []);

  /** 提交登录 */
  const handleSubmit = async (values: LoginFormValues) => {
    setError('');
    setLoading(true);
    try {
      await login(values.employeeId, values.password, values.rememberMe);
      navigate('/dashboard');
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || '工号或密码错误');
    } finally {
      setLoading(false);
    }
  };

  return (
    /* Tailwind 蓝色渐变背景保留用于装饰 */
    <div className="min-h-screen bg-gradient-to-br from-[#0E7F8A] via-[#1B8E99] to-[#9AD0D6] flex flex-col">
      {/* [调整 2026-09-12] 由「水平垂直居中」改为「flex-col + margin:auto」：
          品牌区与登录卡片仍居中，同时为底部宣传标语腾出位置；
          内容高于一屏时 margin:auto 自动归零，页脚随内容下移，不会遮挡卡片 */}
      <div style={{ width: '100%', maxWidth: 420, padding: '0 16px', margin: 'auto' }}>
        {/* Logo & 标题：[新增 2026-09-10] 展示 Logo + 单位名称 + 系统名称 + 单位名称（英） */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          {/* [调整 2026-09-10] 显示框高度固定 64px，宽度随 Logo 原始比例伸缩 */}
          <div
            style={{
              height: 64,
              width: 'fit-content',
              maxWidth: '100%',
              padding: '0 16px',
              borderRadius: token.borderRadiusLG,
              background: token.colorBgContainer,
              boxShadow: token.boxShadowTertiary,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
              overflow: 'hidden',
            }}
          >
            <BrandLogo height={40} />
          </div>
          <Title level={2} style={{ color: token.colorTextLightSolid, marginBottom: 2, fontWeight: 'bold' }}>
            {branding.orgNameCn}
          </Title>
          <Text style={{ color: token.colorTextLightSolid, fontSize: token.fontSizeLG, opacity: 0.92, display: 'block' }}>
            {branding.systemName}
          </Text>
          <Text style={{ color: token.colorTextLightSolid, fontSize: token.fontSizeSM, opacity: 0.7 }}>
            {branding.orgNameEn}
          </Text>
        </div>

        {/* 登录卡片 */}
        <Card>
          <Title level={4} style={{ marginBottom: token.marginLG }}>
            账号登录
          </Title>

          {/* 错误提示 */}
          {error && (
            <Alert
              message={error}
              type="error"
              showIcon
              closable
              onClose={() => setError('')}
              style={{ marginBottom: 16 }}
            />
          )}

          {/* 登录表单 */}
          <Form<LoginFormValues>
            form={form}
            onFinish={handleSubmit}
            initialValues={{ rememberMe: false }}
            size="large"
          >
            <Form.Item
              name="employeeId"
              rules={[
                { required: true, message: '请输入工号' },
                { pattern: /^[A-Za-z0-9_]+$/, message: '登录账号不能包含空格或标点符号' },
              ]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder="请输入工号"
                maxLength={20}
                autoFocus
                // [修复 2026-09-05] 补充 autocomplete：消除浏览器「表单缺少自动填充属性」可访问性告警
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                // [修复 2026-09-05] 补充 autocomplete：消除浏览器自动填充可访问性告警
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item name="rememberMe" valuePropName="checked">
              <Checkbox>记住我（3天内自动登录）</Checkbox>
            </Form.Item>

            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                size="large"
              >
                登录
              </Button>
            </Form.Item>
          </Form>

          {/* 帮助提示 + 注册入口 */}
          <div style={{ textAlign: 'center', paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              忘记用户名密码或无法登录时请联系管理员
            </Text>
            {regEnabled && (
              <div style={{ marginTop: 8 }}>
                <Link to="/register">还没有账号？提交注册申请</Link>
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* [新增 2026-09-12] 宣传标语：固定贴浏览器窗口底部（决策 2 方案 B）。
          采用正常文档流而非 position:fixed —— 内容高于一屏时会自然下移，
          既保持「贴底」观感，又不会像 fixed 那样在小高度窗口下覆盖登录卡片。
          未配置或管理员主动清空时整块不渲染 */}
      {branding.slogan && (
        <div style={{ padding: '0 16px 24px', textAlign: 'center', flexShrink: 0 }}>
          <Text
            style={{
              color: token.colorTextLightSolid,
              fontSize: token.fontSizeSM,
              opacity: 0.85,
              letterSpacing: 0.3,
            }}
          >
            {branding.slogan}
          </Text>
        </div>
      )}
    </div>
  );
};

export default Login;
