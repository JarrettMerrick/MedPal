// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 科室详情页（信息 + 人员统计 + 特色技术/设备 + 修改记录）。
 * [改进] 手写 div → Card/Descriptions/Tag/Modal.confirm
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { Card, Descriptions, Tag, Button, Spin, Row, Col, Typography, Space, Empty, theme, App } from 'antd';
import { EditOutlined, DeleteOutlined, DownloadOutlined } from '@ant-design/icons';
import { getDepartment, deleteDepartment, getDepartmentStaffStats } from '../../api/departments';
import { useAuth } from '../../contexts/AuthContext';
import { getOriginalUrl } from '../../utils/imageUtils';
import SafeImage from '../../components/SafeImage';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import type { Department } from '../../types/department';
// [调整 2026-09-15] 新增导入 PERM_DEPT_VIEW / PERM_DEPT_VIEW_HISTORY：修改历史按钮与后端接口权限保持一致
import { hasPermission, PERM_DEPT_EDIT, PERM_DEPT_DELETE, PERM_DEPT_VIEW, PERM_DEPT_VIEW_HISTORY } from '../../utils/permissions';
// [新增 2026-09-15] 修改历史查询按钮：查看最近三次修改的字段级前后对比
import ModificationHistoryButton from '../../components/ModificationHistoryButton';

const { Title, Text } = Typography;
const { useToken } = theme;

const DepartmentDetail: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams<{ id: string }>();
  const { token } = useToken();
  const { user } = useAuth();
  const [department, setDepartment] = useState<Department | null>(null);
  const [staffStats, setStaffStats] = useState<{ category: string; titles: Record<string, number>; total: number } | null>(null);
  const [loading, setLoading] = useState(true);

  // [改进] 获取来源页面URL，用于返回按钮恢复原始状态
  const returnTo = (location.state as any)?.returnTo as string | undefined;

  const canEdit = department ? hasPermission(user, PERM_DEPT_EDIT) : false;
  const canDelete = hasPermission(user, PERM_DEPT_DELETE);
  // [调整 2026-09-15] 修改历史查询入口的显隐：与后端 /api/audit/history 校验一致——
  // 需 department.view + department.view_history（「修改历史」独立权限，默认仅超级管理员拥有），
  // 避免无权限用户看到按钮、点击后报 403
  const canViewHistory = hasPermission(user, PERM_DEPT_VIEW) && hasPermission(user, PERM_DEPT_VIEW_HISTORY);
  const { modal } = App.useApp();

  useEffect(() => {
    if (id) {
      const deptId = Number(id);
      getDepartment(deptId).then((data) => { setDepartment(data); setLoading(false); }).catch(() => setLoading(false));
      getDepartmentStaffStats(deptId).then(setStaffStats).catch(() => {});
    }
  }, [id]);

  const handleDelete = () => {
    modal.confirm({
      title: '确定要删除该科室吗？',
      content: '删除后数据无法恢复，是否继续？',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => { try { await deleteDepartment(Number(id)); navigate(returnTo || '/departments'); } catch { /* ignore */ } },
    });
  };

  const downloadImage = async (path: string, filename: string) => {
    try {
      // [改进] 下载文件名后缀以数据库记录的真实路径为准（如 .png），避免 PNG 被下载成 .jpg。
      const realExt = path.includes('.') ? path.slice(path.lastIndexOf('.')) : '.jpg';
      let base = filename.includes('.') ? filename.slice(0, filename.lastIndexOf('.')) : filename;
      // [改进] 清洗 Windows 文件名非法字符（/\:*?"<>|）及首尾空白/点，
      // 避免技术/设备名称或备注含特殊字符导致下载文件名异常或失败；全空兜底"图片"。
      base = base.replace(/[\\/:*?"<>|]/g, '_').replace(/^[\s.]+|[\s.]+$/g, '') || '图片';
      const finalName = `${base}${realExt}`;
      const url = getOriginalUrl(path) || '';
      const resp = await fetch(url);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = finalName;
      a.click(); URL.revokeObjectURL(a.href);
    } catch { /* silent */ }
  };

  const categoryColorMap: Record<string, string> = { '护理病区': 'purple', '行政科室': 'green', '临床专科': 'blue' };

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;
  if (!department) return <div style={{ textAlign: 'center', padding: 80, color: 'var(--text-3)' }}>科室信息不存在</div>;

  return (
    <PageContainer maxWidth={960}>
      <PageHeader
        title="科室详情"
        onBack={() => navigate(returnTo || '/departments')}
        extra={(
          <Space>
            {/* [新增 2026-09-15] 修改历史查询：置于「编辑」左侧，展示最近三次修改的字段级前后对比 */}
            {canViewHistory && (
              <ModificationHistoryButton
                entityType="department"
                entityId={department.id}
                entityName={department.name}
              />
            )}
            {canEdit && <Button icon={<EditOutlined />} onClick={() => navigate(`/departments/edit/${department.id}`, { state: { returnTo } })}>编辑</Button>}
            {canDelete && <Button danger icon={<DeleteOutlined />} onClick={handleDelete}>删除</Button>}
          </Space>
        )}
      />

      <Card style={{ marginBottom: 16 }}>
        {/* [调整 2026-09-11] 原「变更历史」区块随信息修改功能下线删除 */}
        {/* [调整 2026-09-15] 修改记录改由页头「修改历史」按钮按需查看（最近三次，含字段前后对比） */}
        {/* 基本信息 */}
        <Descriptions column={2} size="small" style={{ marginTop: 8 }}>
          <Descriptions.Item label="科室名称"><Text strong style={{ fontSize: 16 }}>{department.name}</Text></Descriptions.Item>
          <Descriptions.Item label="科室ID">{department.id}</Descriptions.Item>
          <Descriptions.Item label="分类">
            <Tag color={categoryColorMap[department.category] || 'default'}>{department.category}</Tag>
          </Descriptions.Item>
        </Descriptions>

        {/* 人员统计 */}
        {staffStats && (
          <Card size="small" style={{ marginTop: token.marginMD, background: token.colorFillQuaternary }}>
            <Text strong style={{ fontSize: token.fontSizeSM }}>
              {department.category === '护理病区' ? '护理人员' : '医技人员'}构成
            </Text>
            <div style={{ marginTop: token.marginSM, display: 'flex', flexWrap: 'wrap', gap: `8px ${token.marginXL}px` }}>
              {Object.entries(staffStats.titles).map(([title, count]) => (
                <Text key={title}>{title}: <Text strong style={{ color: token.colorPrimary }}>{count}</Text>人</Text>
              ))}
              <Text>总计: <Text strong>{staffStats.total}</Text>人</Text>
            </div>
          </Card>
        )}

        {/* 科室合照 */}
        <div style={{ marginTop: token.marginMD }}>
          <Title level={5}>科室合照</Title>
          {department.group_photo ? (
            <div style={{ position: 'relative', display: 'inline-block' }} className="dept-detail-image">
              <SafeImage src={department.group_photo} alt="科室合照" style={{ maxWidth: 400, borderRadius: token.borderRadius }} />
              <Button size="small" icon={<DownloadOutlined />} style={{ position: 'absolute', bottom: token.marginSM, right: token.marginSM, opacity: 0 }} onClick={() => downloadImage(department.group_photo!, `科室合照-${department.name}.jpg`)}>下载</Button>
            </div>
          ) : (
            <div style={{ border: `1px dashed ${token.colorBorder}`, borderRadius: token.borderRadius, padding: token.paddingMD, display: 'flex', alignItems: 'center', gap: token.marginMD, color: token.colorTextTertiary }}>
              <Empty description={false} image={Empty.PRESENTED_IMAGE_SIMPLE} />
              <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>暂未上传，请在编辑页面上传</Text>
            </div>
          )}
        </div>

        {/* 科室介绍 */}
        <div style={{ marginTop: token.marginMD }}>
          <Title level={5}>科室介绍</Title>
          <Text style={{ whiteSpace: 'pre-wrap' }}>{department.description || '-'}</Text>
        </div>
      </Card>

      {/* 特色技术 */}
      <Card title="科室特色技术" style={{ marginBottom: token.marginMD }}>
        {!department.specialties?.length ? (
          <Empty description="暂无特色技术" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div>
            {department.specialties.map((spec, index) => (
              <Card key={spec.id || index} size="small" style={{ marginBottom: token.marginSM }}>
                <Space align="start">
                  <Tag color="blue">{index + 1}</Tag>
                  <div>
                    <Text strong>{spec.name}</Text>
                    {spec.detail && <Text style={{ display: 'block', whiteSpace: 'pre-wrap', marginTop: token.marginXS }}>{spec.detail}</Text>}
                    {spec.images?.length && (
                      <Row gutter={token.marginSM} style={{ marginTop: token.marginSM }}>
                        {spec.images.map((img) => (
                          <Col key={img.id}>
                            <div className="dept-detail-image" style={{ position: 'relative' }}>
                              <SafeImage src={img.image_url} alt={img.caption || ''} style={{ width: 160, height: 120, objectFit: 'contain', background: token.colorFillQuaternary, borderRadius: token.borderRadius }} />
                              <Button size="small" icon={<DownloadOutlined />} style={{ position: 'absolute', inset: 0, margin: 'auto', opacity: 0, width: 'fit-content', height: 'fit-content' }} onClick={() => downloadImage(img.image_url, img.caption ? `${spec.name}-${img.caption}` : (spec.name || '技术图片'))}>下载</Button>
                              {img.caption && <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block', textAlign: 'center' }}>{img.caption}</Text>}
                            </div>
                          </Col>
                        ))}
                      </Row>
                    )}
                  </div>
                </Space>
              </Card>
            ))}
          </div>
        )}
      </Card>

      {/* 特色设备 */}
      <Card title="科室特色设备" style={{ marginBottom: token.marginMD }}>
        {!department.equipments?.length ? (
          <Empty description="暂无特色设备" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div>
            {department.equipments.map((equip, index) => (
              <Card key={equip.id || index} size="small" style={{ marginBottom: token.marginSM }}>
                <Space align="start">
                  <Tag color="blue">{index + 1}</Tag>
                  <div style={{ flex: 1 }}>
                    <Text strong>{equip.name}</Text>
                    {equip.model && <Text type="secondary" style={{ display: 'block' }}>型号：{equip.model}</Text>}
                    {equip.function_description && <Text style={{ display: 'block', whiteSpace: 'pre-wrap', marginTop: token.marginXS }}>功能：{equip.function_description}</Text>}
                    {equip.features && <Text style={{ display: 'block', whiteSpace: 'pre-wrap', marginTop: token.marginXS }}>特点：{equip.features}</Text>}
                    {equip.images?.length && (
                      <Row gutter={token.marginSM} style={{ marginTop: token.marginSM }}>
                        {equip.images.map((img) => (
                          <Col key={img.id}>
                            <div className="dept-detail-image" style={{ position: 'relative' }}>
                              <SafeImage src={img.image_url} alt={img.caption || ''} style={{ width: 160, height: 120, objectFit: 'contain', background: token.colorFillQuaternary, borderRadius: token.borderRadius }} />
                              <Button size="small" icon={<DownloadOutlined />} style={{ position: 'absolute', inset: 0, margin: 'auto', opacity: 0, width: 'fit-content', height: 'fit-content' }} onClick={() => downloadImage(img.image_url, img.caption ? `${equip.name}-${img.caption}` : (equip.name || '设备图片'))}>下载</Button>
                              {img.caption && <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block', textAlign: 'center' }}>{img.caption}</Text>}
                            </div>
                          </Col>
                        ))}
                      </Row>
                    )}
                  </div>
                </Space>
              </Card>
            ))}
          </div>
        )}
      </Card>

      <style>{`
        .dept-detail-image:hover > button { opacity: 1 !important; }
      `}</style>
    </PageContainer>
  );
};

export default DepartmentDetail;
