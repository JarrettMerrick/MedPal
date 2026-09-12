// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 密码修改模态框组件，支持两种模式：
 * 1. 普通模式：用户主动点击"修改密码"，可取消
 * 2. 强制模式（forceMode）：首次登录强制修改密码，不可取消，修改成功后进入系统
 * 
 * 改造说明（v1.1.0）：
 * - [改进] 手写 div 遮罩 → Ant Design Modal 组件
 * - [改进] 手写 input + useState 表单 → Ant Design Form 声明式表单
 * - [改进] 手动校验逻辑 → Form.Item rules 声明式校验
 * - [改进] 手写按钮 → Button 组件 + loading 状态
 * - 业务逻辑不变：API 调用、校验规则、密码比对
 */

import React, { useState } from 'react';
import { Modal, Form, Input, Button, Alert, Typography } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { changePassword } from '../api/auth';
import { useAuth } from '../contexts/AuthContext';

const { Text } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
  /** 首次登录强制修改模式，不允许取消 */
  forceMode?: boolean;
}

/** 密码修改表单字段类型 */
interface ChangePwdFormValues {
  oldPassword: string;
  newPassword: string;
  confirmPassword: string;
}

const ChangePasswordModal: React.FC<Props> = ({ open, onClose, forceMode }) => {
  const { user } = useAuth();
  const [form] = Form.useForm<ChangePwdFormValues>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  /** 提交密码修改 */
  const handleSubmit = async (values: ChangePwdFormValues) => {
    setError('');
    setLoading(true);
    try {
      await changePassword(values.oldPassword, values.newPassword);
      setSuccess(true);
      form.resetFields();
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || '修改失败');
    } finally {
      setLoading(false);
    }
  };

  /** 关闭弹窗并重置状态 */
  const handleClose = () => {
    form.resetFields();
    setError('');
    setSuccess(false);
    onClose();
  };

  return (
    <Modal
      open={open}
      onCancel={!forceMode ? handleClose : undefined}
      footer={null}
      closable={!forceMode}
      maskClosable={false}
      centered
      width={420}
      title={
        <Text strong style={{ fontSize: 16 }}>
          {forceMode ? '首次登录，请修改密码' : '修改密码'}
        </Text>
      }
    >
      {forceMode && (
        <Alert
          message="为了账户安全，请先设置新密码后再继续使用系统。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {success ? (
        /* 修改成功状态 */
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <Text type="success" style={{ fontSize: 16, display: 'block', marginBottom: 16 }}>
            密码修改成功
          </Text>
          <Button
            type="primary"
            onClick={forceMode ? handleClose : () => { form.resetFields(); setSuccess(false); setError(''); onClose(); }}
          >
            {forceMode ? '进入系统' : '关闭'}
          </Button>
        </div>
      ) : (
        /* 修改密码表单 */
        <Form<ChangePwdFormValues>
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          size="large"
        >
          {/* 当前用户（只读展示） */}
          <Form.Item label="当前用户">
            <Input
              value={`${user?.employee_id} - ${user?.name}`}
              disabled
            />
          </Form.Item>

          {/* 原密码 */}
          <Form.Item
            name="oldPassword"
            label="原密码"
            rules={[{ required: true, message: '请输入原密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请输入原密码"
              maxLength={128}
              autoFocus
              // [修复 2026-09-05] 补充 autocomplete：消除浏览器自动填充可访问性告警
              autoComplete="current-password"
            />
          </Form.Item>

          {/* 新密码 */}
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '新密码长度不能少于6位' },
              { max: 50, message: '新密码长度不能超过50位' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('oldPassword') !== value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('新密码不能与原密码相同'));
                },
              }),
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="6-50位"
              maxLength={50}
              // [修复 2026-09-05] 补充 autocomplete：新密码使用 new-password 提示浏览器不要回填旧密码
              autoComplete="new-password"
            />
          </Form.Item>

          {/* 确认新密码 */}
          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的新密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请再次输入新密码"
              maxLength={50}
              // [修复 2026-09-05] 补充 autocomplete：新密码使用 new-password 提示浏览器不要回填旧密码
              autoComplete="new-password"
            />
          </Form.Item>

          {/* 错误提示 */}
          {error && (
            <Alert message={error} type="error" showIcon style={{ marginBottom: 16 }} />
          )}

          {/* 操作按钮 */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
            {!forceMode && (
              <Button onClick={handleClose}>
                取消
              </Button>
            )}
            <Button type="primary" htmlType="submit" loading={loading}>
              确认修改
            </Button>
          </div>
        </Form>
      )}
    </Modal>
  );
};

export default ChangePasswordModal;
