// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 登录页自助注册（公开页面 /register）。
 *
 * - 仅在「账号设置 → 登录页注册」开启时可用；
 * - 提交后进入待审队列，由科室管理员审核，通过后方可登录；
 * - 若该工号上次申请被驳回，提交前会回显驳回原因。
 */
import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Form, Input, Select, Spin, Typography, theme } from 'antd';
import { IdcardOutlined, LockOutlined, UserOutlined, TeamOutlined, ToolOutlined } from '@ant-design/icons';
import { useBranding } from '../../contexts/BrandingContext';
import { getRegistrationOptions, submitRegistration, type RegistrationOptions } from '../../api/registration';
import { getErrorMessage } from '../../utils/format';
import BrandLogo from '../../components/BrandLogo'; // [调整 2026-09-10] 统一 Logo：高度固定、宽度等比

const { Title, Text } = Typography;
const { useToken } = theme;

interface RegisterFormValues {
  employee_id: string;
  name: string;
  password: string;
  confirm_password: string;
  work_type: string;
  department: string;
}

const Register: React.FC = () => {
  const [form] = Form.useForm<RegisterFormValues>();
  const [options, setOptions] = useState<RegistrationOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<{ rejectReason: string | null } | null>(null);
  const branding = useBranding();
  const navigate = useNavigate();
  const { token } = useToken();

  useEffect(() => {
    getRegistrationOptions()
      .then(setOptions)
      .catch((err) => {
        console.error('[register] 获取注册选项失败:', err);
        setOptions({ enabled: false, work_types: [], departments: [] });
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async (values: RegisterFormValues) => {
    setError('');
    setSubmitting(true);
    try {
      const res = await submitRegistration({
        employee_id: values.employee_id.trim(),
        name: values.name.trim(),
        password: values.password,
        work_type: values.work_type,
        department: values.department,
      });
      setDone({ rejectReason: res.last_reject_reason });
    } catch (err) {
      setError(getErrorMessage(err, '提交失败，请稍后再试'));
    } finally {
      setSubmitting(false);
    }
  };

  const brandHeader = (
    <div style={{ textAlign: 'center', marginBottom: 24 }}>
      {/* [调整 2026-09-10] 显示框高度固定 60px，宽度随 Logo 原始比例伸缩 */}
      <div
        style={{
          height: 60, width: 'fit-content', maxWidth: '100%', padding: '0 14px',
          borderRadius: token.borderRadiusLG, background: token.colorBgContainer,
          boxShadow: token.boxShadowTertiary, display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 12px', overflow: 'hidden',
        }}
      >
        <BrandLogo height={36} />
      </div>
      <Title level={3} style={{ color: token.colorTextLightSolid, marginBottom: 2 }}>账号注册</Title>
      <Text style={{ color: token.colorTextLightSolid, opacity: 0.85 }}>
        {branding.orgNameCn} · {branding.systemName}
      </Text>
    </div>
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0E7F8A] via-[#1B8E99] to-[#9AD0D6] flex items-center justify-center py-8">
      <div style={{ width: '100%', maxWidth: 460, padding: '0 16px' }}>
        {brandHeader}

        <Card>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '32px 0' }}><Spin /></div>
          ) : !options?.enabled ? (
            <div>
              <Alert
                type="warning"
                showIcon
                message="暂未开放自助注册"
                description="系统当前未开启登录页注册入口，请联系管理员创建账号。"
              />
              <Button type="primary" block style={{ marginTop: 16 }} onClick={() => navigate('/login')}>
                返回登录
              </Button>
            </div>
          ) : done ? (
            <div>
              <Alert
                type="success"
                showIcon
                message="申请已提交"
                description="请等待科室管理员审核，审核通过后即可使用注册的工号与密码登录。"
              />
              {done.rejectReason && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginTop: 12 }}
                  message="该工号上次申请被驳回"
                  description={`驳回原因：${done.rejectReason}`}
                />
              )}
              <Button type="primary" block style={{ marginTop: 16 }} onClick={() => navigate('/login')}>
                返回登录
              </Button>
            </div>
          ) : (
            <>
              {error && (
                <Alert message={error} type="error" showIcon closable onClose={() => setError('')} style={{ marginBottom: 16 }} />
              )}
              <Form<RegisterFormValues> form={form} onFinish={handleSubmit} layout="vertical" size="large">
                <Form.Item
                  label="工号（登录账号）"
                  name="employee_id"
                  rules={[
                    { required: true, message: '请输入工号' },
                    { pattern: /^[A-Za-z0-9_]+$/, message: '工号只能包含字母、数字、下划线' },
                  ]}
                >
                  <Input prefix={<IdcardOutlined />} placeholder="请输入工号" maxLength={20} autoComplete="username" />
                </Form.Item>

                <Form.Item label="姓名" name="name" rules={[{ required: true, message: '请输入姓名' }]}>
                  <Input prefix={<UserOutlined />} placeholder="请输入真实姓名" maxLength={50} />
                </Form.Item>

                <Form.Item
                  label="密码"
                  name="password"
                  rules={[{ required: true, message: '请输入密码' }, { min: 6, max: 50, message: '密码长度需为 6~50 位' }]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="请设置密码（6~50 位）" autoComplete="new-password" />
                </Form.Item>

                <Form.Item
                  label="确认密码"
                  name="confirm_password"
                  dependencies={['password']}
                  rules={[
                    { required: true, message: '请再次输入密码' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('password') === value) return Promise.resolve();
                        return Promise.reject(new Error('两次输入的密码不一致'));
                      },
                    }),
                  ]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="请再次输入密码" autoComplete="new-password" />
                </Form.Item>

                <Form.Item label="工种" name="work_type" rules={[{ required: true, message: '请选择工种' }]}>
                  <Select
                    placeholder="请选择工种"
                    suffixIcon={<ToolOutlined />}
                    options={options.work_types.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </Form.Item>

                <Form.Item label="所属科室" name="department" rules={[{ required: true, message: '请选择所属科室' }]}>
                  <Select
                    placeholder="请选择所属科室"
                    showSearch
                    optionFilterProp="label"
                    suffixIcon={<TeamOutlined />}
                    options={options.departments.map((d) => ({ value: d, label: d }))}
                  />
                </Form.Item>

                <Form.Item style={{ marginBottom: 8 }}>
                  <Button type="primary" htmlType="submit" loading={submitting} block>提交注册申请</Button>
                </Form.Item>
              </Form>
              <div style={{ textAlign: 'center', paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
                <Link to="/login">已有账号？返回登录</Link>
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
};

export default Register;
