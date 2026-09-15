// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 系统设置页：单位 Logo 与单位名称（中/英）维护。
 *
 * - 保存后通过 BrandingProvider.refresh() 全局立即生效（登录页、导航栏、工作台、标题与 favicon）；
 * - 未配置时回退内置默认 Logo/文案，行为与改造前一致；
 * - 无 system.config 权限时页面只读（禁用输入与操作按钮）。
 */
import React, { useEffect, useState } from 'react';
import {
  App, Button, Card, Col, Divider, Form, Input, Row, Space, Tag, Typography, Upload, theme,
} from 'antd';
import { ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import { useAuth } from '../../contexts/AuthContext';
import { useBranding } from '../../contexts/BrandingContext';
import { resetBrandLogo, uploadBrandLogo } from '../../api/branding';
import { updateSystemConfig } from '../../api/system-config';
import { hasPermission, PERM_SYSTEM_CONFIG } from '../../utils/permissions';
import { getErrorMessage } from '../../utils/format';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import BrandLogo from '../../components/BrandLogo'; // [调整 2026-09-10] 统一 Logo：高度固定、宽度等比

const { Text, Title } = Typography;
const { useToken } = theme;

// 与后端 branding_service 的约束保持一致
const LOGO_MAX_MB = 2;
const LOGO_MIN_EDGE = 64;
const LOGO_MIME = ['image/png', 'image/jpeg', 'image/webp'];

interface NameFormValues {
  org_name_cn: string;
  org_name_en: string;
  system_name: string;
  // [新增 2026-09-12] 宣传标语（显示在登录页与已登录页面底部，整串可编辑）
  org_slogan: string;
}

/** 读取图片真实尺寸（解码后校验最小边） */
const probeImageSize = (file: File): Promise<{ width: number; height: number }> =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('图片解码失败'));
    };
    img.src = url;
  });

const SystemSettings: React.FC = () => {
  const { user } = useAuth();
  const branding = useBranding();
  const { message, modal } = App.useApp();
  const { token } = useToken();
  const [form] = Form.useForm<NameFormValues>();

  const [savingNames, setSavingNames] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [resetting, setResetting] = useState(false);

  const canEdit = hasPermission(user, PERM_SYSTEM_CONFIG);

  // 品牌配置加载/刷新后回填表单
  useEffect(() => {
    form.setFieldsValue({
      org_name_cn: branding.raw?.org_name_cn ?? '',
      org_name_en: branding.raw?.org_name_en ?? '',
      system_name: branding.raw?.system_name ?? '',
      org_slogan: branding.raw?.slogan ?? '',
    });
  }, [branding.raw, form]);

  /** 上传前置校验：类型 / 大小 / 最小边 */
  const beforeUpload: UploadProps['beforeUpload'] = async (file) => {
    if (!canEdit) return Upload.LIST_IGNORE;
    if (!LOGO_MIME.includes(file.type)) {
      message.error('仅支持 PNG / JPG / WebP 格式的图片');
      return Upload.LIST_IGNORE;
    }
    if (file.size > LOGO_MAX_MB * 1024 * 1024) {
      message.error(`Logo 文件过大，最大允许 ${LOGO_MAX_MB}MB`);
      return Upload.LIST_IGNORE;
    }
    try {
      const { width, height } = await probeImageSize(file);
      if (Math.min(width, height) < LOGO_MIN_EDGE) {
        message.error(`图片尺寸过小，最小边需不小于 ${LOGO_MIN_EDGE}px（当前 ${width}×${height}）`);
        return Upload.LIST_IGNORE;
      }
    } catch {
      message.error('图片文件已损坏或无法解析');
      return Upload.LIST_IGNORE;
    }

    setUploading(true);
    try {
      await uploadBrandLogo(file);
      await branding.refresh();
      message.success('单位 Logo 已更新，全站已生效');
    } catch (err) {
      message.error(getErrorMessage(err, 'Logo 上传失败'));
    } finally {
      setUploading(false);
    }
    return Upload.LIST_IGNORE;
  };

  /** 重置为内置默认 Logo */
  const handleReset = () => {
    modal.confirm({
      title: '确定重置为单位默认 Logo 吗？',
      content: '重置后登录页、导航栏等位置将恢复为系统内置 Logo。',
      okText: '重置',
      okButtonProps: { danger: true },
      onOk: async () => {
        setResetting(true);
        try {
          await resetBrandLogo();
          await branding.refresh();
          message.success('已恢复为默认 Logo');
        } catch (err) {
          message.error(getErrorMessage(err, '重置失败'));
        } finally {
          setResetting(false);
        }
      },
    });
  };

  /** 保存单位名称、系统名称与宣传标语 */
  const handleSaveNames = async () => {
    const values = await form.validateFields();
    setSavingNames(true);
    try {
      await updateSystemConfig('org_name_cn', values.org_name_cn ?? '');
      await updateSystemConfig('org_name_en', values.org_name_en ?? '');
      await updateSystemConfig('system_name', values.system_name ?? '');
      // [新增 2026-09-12] 宣传标语：清空即隐藏，前端不再渲染该区域
      await updateSystemConfig('org_slogan', values.org_slogan ?? '');
      await branding.refresh();
      message.success('名称与标语已保存，全站已生效');
    } catch (err) {
      message.error(getErrorMessage(err, '保存失败'));
    } finally {
      setSavingNames(false);
    }
  };

  // [调整 2026-09-10] 预览口径与实际展示一致：高度固定 72px，宽度按 Logo 原始比例伸缩
  const logoPreview = <BrandLogo height={72} style={{ maxWidth: '100%' }} />;

  const checkerBoard: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 148,
    borderRadius: token.borderRadiusLG,
    border: `1px solid ${token.colorBorderSecondary}`,
    backgroundImage:
      'linear-gradient(45deg, #F0F2F5 25%, transparent 25%), linear-gradient(-45deg, #F0F2F5 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #F0F2F5 75%), linear-gradient(-45deg, transparent 75%, #F0F2F5 75%)',
    backgroundSize: '16px 16px',
    backgroundPosition: '0 0, 0 8px, 8px -8px, -8px 0px',
  };

  return (
    <PageContainer>
      <PageHeader title="单位设置" />

      <div style={{ marginBottom: token.marginMD }}>
        <Text type="secondary">
          维护单位 Logo 与单位名称，保存后统一应用于登录页、导航栏、工作台以及浏览器标题与页签图标。
        </Text>
        <Tag color={canEdit ? 'green' : 'default'} style={{ marginLeft: token.marginXS }}>
          {canEdit ? '可编辑' : '只读'}
        </Tag>
      </div>

      <Row gutter={[token.marginMD, token.marginMD]}>
        {/* 单位 Logo */}
        <Col xs={24} lg={12}>
          <Card title="单位 Logo" style={{ height: '100%' }}>
            <Row gutter={token.marginMD} align="middle">
              <Col xs={24} sm={10} style={{ marginBottom: token.marginSM }}>
                <div style={checkerBoard}>{logoPreview}</div>
              </Col>
              <Col xs={24} sm={14}>
                <Space direction="vertical" size={token.marginSM} style={{ width: '100%' }}>
                  <Upload
                    accept="image/png,image/jpeg,image/webp"
                    showUploadList={false}
                    beforeUpload={beforeUpload}
                    disabled={!canEdit || uploading}
                  >
                    <Button type="primary" icon={<UploadOutlined />} loading={uploading} disabled={!canEdit}>
                      上传 Logo
                    </Button>
                  </Upload>
                  <Button
                    icon={<ReloadOutlined />}
                    onClick={handleReset}
                    loading={resetting}
                    disabled={!canEdit || !branding.raw?.logo_url}
                  >
                    重置为默认
                  </Button>
                  <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block' }}>
                    支持 PNG / JPG / WebP；不超过 {LOGO_MAX_MB}MB；最小边不小于 {LOGO_MIN_EDGE}px；建议透明底 PNG。
                    全站统一按「显示高度固定、宽度按原图比例自适应」展示，横版 / 竖版 Logo 均不会被拉伸变形。
                  </Text>
                </Space>
              </Col>
            </Row>
          </Card>
        </Col>

        {/* 单位名称 */}
        <Col xs={24} lg={12}>
          <Card title="单位名称与系统名称" style={{ height: '100%' }}>
            <Form<NameFormValues> form={form} layout="vertical" disabled={!canEdit}>
              <Form.Item
                label="单位名称（中文）"
                name="org_name_cn"
                rules={[{ max: 100, message: '最多 100 个字符' }]}
              >
                <Input placeholder="例如：某某医院" maxLength={100} showCount allowClear />
              </Form.Item>
              <Form.Item
                label="单位名称（英文）"
                name="org_name_en"
                rules={[{ max: 150, message: '最多 150 个字符' }]}
              >
                <Input placeholder="例如：XXX Hospital" maxLength={150} showCount allowClear />
              </Form.Item>
              <Divider style={{ margin: `${token.marginXS}px 0 ${token.marginMD}px` }}>系统名称</Divider>
              <Form.Item
                label="系统名称"
                name="system_name"
                extra="显示在登录页与系统首页的标题行；留空将回退为内置默认名称。"
                rules={[{ max: 100, message: '最多 100 个字符' }]}
              >
                <Input placeholder="例如：XX医院信息管理系统" maxLength={100} showCount allowClear />
              </Form.Item>
              {/* [新增 2026-09-12] 宣传标语：登录页与已登录页面底部展示，整串可编辑 */}
              <Form.Item
                label="宣传标语（Slogan）"
                name="org_slogan"
                extra="显示在登录页与已登录页面的底部；整串均可编辑（含「MedPal —」前缀），留空则隐藏该区域。仅支持纯文本，不支持富文本。"
                rules={[{ max: 100, message: '最多 100 个字符' }]}
              >
                <Input
                  placeholder="例如：MedPal — 让医院宣传更有序、更高效。"
                  maxLength={100}
                  showCount
                  allowClear
                />
              </Form.Item>
              <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block', marginBottom: token.marginSM }}>
                单位名称用于登录页品牌区、导航栏与工作台；系统名称用于登录页与首页的标题行；
                宣传标语用于登录页与已登录页面的底部。留空项将显示内置默认文案（标语留空则不显示）。
              </Text>
              <Space>
                <Button type="primary" loading={savingNames} onClick={handleSaveNames} disabled={!canEdit}>
                  保存
                </Button>
                <Button
                  onClick={() =>
                    form.setFieldsValue({
                      org_name_cn: branding.raw?.org_name_cn ?? '',
                      org_name_en: branding.raw?.org_name_en ?? '',
                      system_name: branding.raw?.system_name ?? '',
                      org_slogan: branding.raw?.slogan ?? '',
                    })
                  }
                  disabled={!canEdit}
                >
                  取消
                </Button>
              </Space>
            </Form>
          </Card>
        </Col>
      </Row>

      {/* 全局效果预览 */}
      <Card title="全局效果预览" style={{ marginTop: token.marginMD }}>
        <Row gutter={[token.marginLG, token.marginMD]}>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>登录页品牌区</Text>
            <div
              style={{
                marginTop: token.marginSM,
                padding: token.paddingLG,
                borderRadius: token.borderRadiusLG,
                textAlign: 'center',
                background: 'linear-gradient(135deg, #0E7F8A, #1B8E99 55%, #9AD0D6)',
                color: '#fff',
              }}
            >
              {/* [调整 2026-09-10] 与登录页保持一致：高度固定 64px，宽度随 Logo 比例伸缩 */}
              <div
                style={{
                  height: 64, width: 'fit-content', maxWidth: '100%', padding: '0 16px',
                  margin: '0 auto 12px', borderRadius: 14,
                  background: 'rgba(255,255,255,0.92)', display: 'flex',
                  alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
                }}
              >
                <BrandLogo height={40} />
              </div>
              <Title level={4} style={{ color: '#fff', margin: 0, fontWeight: 700 }}>
                {branding.orgNameCn}
              </Title>
              <div style={{ color: '#fff', opacity: 0.9, marginTop: 4 }}>{branding.systemName}</div>
              <Text style={{ color: '#fff', opacity: 0.72, fontSize: token.fontSizeSM, display: 'block', marginTop: 6 }}>
                {branding.orgNameEn}
              </Text>
              {/* [新增 2026-09-12] 标语预览：与实际登录页一致，标语位于页面最底部 */}
              {branding.slogan && (
                <div
                  style={{
                    marginTop: token.marginMD,
                    paddingTop: token.marginSM,
                    borderTop: '1px solid rgba(255,255,255,0.28)',
                    fontSize: token.fontSizeSM,
                    opacity: 0.85,
                  }}
                >
                  {branding.slogan}
                </div>
              )}
            </div>
          </Col>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>导航栏页头</Text>
            <div
              style={{
                marginTop: token.marginSM,
                height: 64,
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '0 16px',
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: token.borderRadiusLG,
                background: '#fff',
              }}
            >
              {/* [调整 2026-09-10] 与导航栏保持一致：高度固定 34px，宽度随 Logo 比例伸缩 */}
              <div
                style={{
                  height: 34, minWidth: 34, width: 'fit-content', maxWidth: 140,
                  borderRadius: 10, overflow: 'hidden', padding: '0 6px',
                  background: 'linear-gradient(135deg, #0E7F8A, #0A6771)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}
              >
                <BrandLogo height={22} />
              </div>
              <Text strong style={{ fontSize: 15 }}>{branding.orgNameCn}</Text>
            </div>
          </Col>
        </Row>
      </Card>
    </PageContainer>
  );
};

export default SystemSettings;
