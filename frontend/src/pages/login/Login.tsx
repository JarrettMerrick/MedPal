// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 登录页面，系统唯一不需要登录的公开路由。
 * 支持工号+密码登录，可选"记住我"（3 天内自动登录）。
 * 登录成功后跳转至 /dashboard（待审核账号跳转 /profile，见下方说明）。
 *
 * [重构 2026-09-17] 排版方案：左右分栏（AuthLayout）
 * --------------------------------------------------
 * 原方案「整页渐变 + 居中单卡片」在大屏下左右两侧出现大片纯色空白，结构单薄。
 * 本次参考现代 SaaS / 医疗系统的通行做法改为分栏：
 *   左：品牌展示区 —— 渐变底 + 医疗图形装饰（圆环/点阵/十字/ECG 心跳线）+
 *       Logo / 单位名称 / 系统名称 / 英文名 / 宣传标语；空白由图形填充而非留白；
 *   右：表单区 —— 纯白背景直铺（不再套卡片，去掉冗余层级），内容垂直居中：
 *       ① 标题区（欢迎回来 26/700 + 辅助说明 14/次级灰）
 *       ② 表单（工号 / 密码 / 记住我 / 登录）
 *       ③ 注册入口（分隔线 + 全宽描边按钮，登录 / 注册层级清晰）
 *       ④ 帮助提示条（常驻，注册关闭时承担收尾，避免底部空洞）
 *
 * 响应式：<992px 折叠为「顶部品牌条 + 表单区」（见 global.css）。
 * 控件统一 46px 高（ConfigProvider 局部覆盖 controlHeightLG），触控与桌面一致。
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Checkbox, ConfigProvider, Divider, Form, Input, Typography, theme } from 'antd';
import { LockOutlined, UserAddOutlined, UserOutlined } from '@ant-design/icons';

import { useAuth } from '../../contexts/AuthContext';
import { getRegistrationOptions } from '../../api/registration';
import AuthLayout from '../../components/AuthLayout';

const { Text } = Typography;
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
  const navigate = useNavigate();
  const { token } = useToken();
  // [新增 2026-09-10] 注册开关：开启时展示注册入口，关闭时整块不渲染（不留占位）
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
      const loggedUser = await login(values.employeeId, values.password, values.rememberMe);
      // [新增 2026-09-17] 待审核账号（自助注册后尚未通过审核）直接进入「个人信息」页：
      // 后端此时仅放行本人资料相关接口，避免先跳工作台再被重定向的闪烁
      navigate(loggedUser.review_status === 'pending' ? '/profile' : '/dashboard');
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || '工号或密码错误');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout formWidth={400}>
      {/* 局部统一大号控件高度（46px）：输入框与按钮等高等宽，视觉更稳 */}
      <ConfigProvider theme={{ token: { controlHeightLG: 46 } }}>
        {/* ① 标题区 */}
        <div style={{ marginBottom: 30 }}>
          <h2 className="auth-form-title">欢迎回来</h2>
          <p className="auth-form-subtitle">请使用工号与密码登录系统</p>
        </div>

        {/* ② 错误提示 */}
        {error && (
          <Alert
            message={error}
            type="error"
            showIcon
            closable
            onClose={() => setError('')}
            style={{ marginBottom: 18 }}
          />
        )}

        {/* ② 登录表单 */}
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

          <Form.Item name="rememberMe" valuePropName="checked" style={{ marginBottom: 22 }}>
            <Checkbox>记住我（3天内自动登录）</Checkbox>
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              size="large"
              // 阴影交由 .auth-neu 的新拟态样式统一控制（凸起 → 按压时内凹）
              style={{ fontSize: 15, fontWeight: 600 }}
            >
              登录
            </Button>
          </Form.Item>
        </Form>

        {/* ③ 注册入口 + ④ 帮助提示（注册开 / 关两种状态均结构完整） ──
            开启：分隔线（还没有账号？）+ 全宽描边按钮，视觉层级明确、第一眼可见；
            关闭：整块不渲染、不留占位，由下方常驻提示条承担收尾 */}
        <div style={{ marginTop: 28 }}>
          {regEnabled && (
            <>
              <Divider plain style={{ margin: '0 0 18px', fontSize: 12, color: token.colorTextTertiary }}>
                还没有账号？
              </Divider>
              <Button
                className="login-register-btn"
                block
                size="large"
                icon={<UserAddOutlined />}
                onClick={() => navigate('/register')}
              >
                提交注册申请
              </Button>
            </>
          )}
          {/* 常驻提示条：注册关闭时作为表单区唯一收尾元素，避免底部空洞 / 上重下轻 */}
          <div className="login-help-note" style={{ marginTop: regEnabled ? 18 : 0 }}>
            <Text type="secondary" style={{ fontSize: 12.5 }}>
              忘记用户名密码或无法登录时，请联系管理员
            </Text>
          </div>
        </div>
      </ConfigProvider>
    </AuthLayout>
  );
};

export default Login;
