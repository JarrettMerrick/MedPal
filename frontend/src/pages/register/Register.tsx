// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 登录页自助注册（公开页面 /register）。
 *
 * - 仅在「账号设置 → 登录页注册」开启时可用；
 * - [调整 2026-09-17] **注册成功即可登录**（完善个人资料），
 *   审核通过后解锁该角色的完整权限；被驳回可重新提交（回显驳回原因）；
 * - 工号为 6 位数字（与后端 registration_service 的校验保持一致）。
 *
 * [重构 2026-09-17 · 新拟态] 与登录页共用 AuthLayout 左右分栏布局。
 *
 * [调整 2026-09-17 · 一屏内完成] 注册字段共 6 项，原先单列纵排使页面过高、
 * 需要滚动才能看到提交按钮。现改为**桌面双列**（工号/姓名、密码/确认密码、
 * 工种/科室各占一行两列）+ **紧凑尺寸**（标题 22、标签 13、控件 42、间距 14），
 * 整体高度约 400px，常见笔记本视口可完整呈现；
 * 窄屏（<576px）由 antd 的 Col 响应式规则自动回退为单列。
 */

import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Alert, Button, Col, ConfigProvider, Form, Input, Row, Select, Spin, Typography } from 'antd';
import { IdcardOutlined, LockOutlined, UserOutlined, TeamOutlined, ToolOutlined } from '@ant-design/icons';

import { getRegistrationOptions, submitRegistration, type RegistrationOptions } from '../../api/registration';
import { getErrorMessage } from '../../utils/format';
import AuthLayout from '../../components/AuthLayout';

const { Text } = Typography;

interface RegisterFormValues {
  employee_id: string;
  name: string;
  password: string;
  confirm_password: string;
  work_type: string;
  department: string;
}

/** 双列栅格：桌面占半宽，窄屏占满（antd 响应式断点） */
const HALF = { xs: 24, sm: 12 } as const;

const Register: React.FC = () => {
  const [form] = Form.useForm<RegisterFormValues>();
  const [options, setOptions] = useState<RegistrationOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<{ rejectReason: string | null } | null>(null);
  const navigate = useNavigate();

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

  return (
    /* 表单区加宽到 560px 以容纳双列；.auth-dense 提供注册页的紧凑排版参数 */
    <AuthLayout formWidth={560}>
      <div className="auth-dense">
        {/* 局部统一控件高度 42px（比登录页更紧凑，保证一屏内完成填写） */}
        <ConfigProvider theme={{ token: { controlHeightLG: 42 } }}>
          {/* 标题区（紧凑档：主标题 22/700 + 辅助说明 13/次级灰） */}
          <div style={{ marginBottom: 22 }}>
            <h2 className="auth-form-title">创建账号</h2>
            <p className="auth-form-subtitle">提交后即可登录完善个人资料，审核通过后解锁完整权限</p>
          </div>

          {loading ? (
            <div style={{ textAlign: 'center', padding: '48px 0' }}>
              <Spin />
            </div>
          ) : !options?.enabled ? (
            /* ① 未开放自助注册 */
            <div>
              <Alert
                type="warning"
                showIcon
                message="暂未开放自助注册"
                description="系统当前未开启登录页注册入口，请联系管理员创建账号。"
              />
              <Button type="primary" block size="large" style={{ marginTop: 20 }} onClick={() => navigate('/login')}>
                返回登录
              </Button>
            </div>
          ) : done ? (
            /* ② 提交成功 */
            <div>
              {/* [调整 2026-09-17] 注册成功即可登录：账号已创建（待审核态），
                  审核通过前仅可查看/修改个人信息，通过后解锁完整权限 */}
              <Alert
                type="success"
                showIcon
                message="注册成功，可直接登录"
                description="账号已创建，请使用刚设置的工号与密码登录。审核通过前仅可查看和修改个人信息，审核通过后解锁完整权限。"
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
              <Button type="primary" block size="large" style={{ marginTop: 20 }} onClick={() => navigate('/login')}>
                返回登录
              </Button>
            </div>
          ) : (
            /* ③ 注册表单（桌面双列 / 窄屏单列） */
            <>
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
              <Form<RegisterFormValues> form={form} onFinish={handleSubmit} layout="vertical" size="large">
                {/* 第一行：工号 + 姓名 */}
                <Row gutter={16}>
                  <Col {...HALF}>
                    <Form.Item
                      label="工号（登录账号）"
                      name="employee_id"
                      // [调整 2026-09-17] 工号规则收紧为 6 位数字（与后端 registration_service 一致）
                      rules={[
                        { required: true, message: '请输入工号' },
                        { pattern: /^\d{6}$/, message: '工号为 6 位数字' },
                      ]}
                    >
                      <Input
                        prefix={<IdcardOutlined />}
                        placeholder="6 位数字工号"
                        maxLength={6}
                        inputMode="numeric"
                        autoComplete="username"
                      />
                    </Form.Item>
                  </Col>
                  <Col {...HALF}>
                    <Form.Item label="姓名" name="name" rules={[{ required: true, message: '请输入姓名' }]}>
                      <Input prefix={<UserOutlined />} placeholder="真实姓名" maxLength={50} />
                    </Form.Item>
                  </Col>
                </Row>

                {/* 第二行：密码 + 确认密码 */}
                <Row gutter={16}>
                  <Col {...HALF}>
                    <Form.Item
                      label="密码"
                      name="password"
                      rules={[
                        { required: true, message: '请输入密码' },
                        { min: 6, max: 50, message: '密码长度需为 6~50 位' },
                      ]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="6~50 位" autoComplete="new-password" />
                    </Form.Item>
                  </Col>
                  <Col {...HALF}>
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
                      <Input.Password prefix={<LockOutlined />} placeholder="再次输入密码" autoComplete="new-password" />
                    </Form.Item>
                  </Col>
                </Row>

                {/* 第三行：工种 + 所属科室 */}
                <Row gutter={16}>
                  <Col {...HALF}>
                    <Form.Item label="工种" name="work_type" rules={[{ required: true, message: '请选择工种' }]}>
                      <Select
                        placeholder="请选择工种"
                        suffixIcon={<ToolOutlined />}
                        options={options.work_types.map((o) => ({ value: o.value, label: o.label }))}
                      />
                    </Form.Item>
                  </Col>
                  <Col {...HALF}>
                    <Form.Item label="所属科室" name="department" rules={[{ required: true, message: '请选择所属科室' }]}>
                      <Select
                        placeholder="请选择所属科室"
                        showSearch
                        optionFilterProp="label"
                        suffixIcon={<TeamOutlined />}
                        options={options.departments.map((d) => ({ value: d, label: d }))}
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Form.Item style={{ marginBottom: 0 }}>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={submitting}
                    block
                    // 阴影交由 .auth-neu 的新拟态样式统一控制（凸起 → 按压时内凹）
                    style={{ fontWeight: 600 }}
                  >
                    提交注册申请
                  </Button>
                </Form.Item>
              </Form>

              {/* 底部切换：与登录页的「帮助提示条」位置对应 */}
              <div style={{ marginTop: 18, textAlign: 'center', fontSize: 13 }}>
                <Text type="secondary">已有账号？</Text>
                <Link to="/login" style={{ marginLeft: 4 }}>返回登录</Link>
              </div>
            </>
          )}

          {/* 未开放状态下的补充说明（指引管理员如何开启） */}
          {!loading && !done && options?.enabled === false && (
            <Text type="secondary" style={{ display: 'block', marginTop: 14, fontSize: 12.5, textAlign: 'center' }}>
              如需开通自助注册，请联系系统管理员在「账号设置」中开启
            </Text>
          )}
        </ConfigProvider>
      </div>
    </AuthLayout>
  );
};

export default Register;
