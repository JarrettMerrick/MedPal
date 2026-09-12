// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 制度详情页（含富文本渲染 + 修改历史）。
 * [改进] 手写 div → Card/Tag/Timeline，权鉴 → LockOutlined 无权限提示
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { Card, Descriptions, Tag, Button, Typography, Spin, Timeline, Modal, App } from 'antd';
import { EditOutlined, ClockCircleOutlined, EyeOutlined } from '@ant-design/icons';
import { getRegulation, getRegulationHistoryDetail } from '../../api/regulations';
import type { Regulation, RegulationHistory } from '../../types/regulation';
import { formatDateTime } from '../../utils/time';
// [修复 2026-09-09] 统一富文本渲染容器：制度正文/历史版本与编辑器预览口径一致
import RichTextContent from '../../components/RichTextContent';
import { useAuth } from '../../contexts/AuthContext';
import { hasPermission, PERM_REGULATION_EDIT } from '../../utils/permissions';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text } = Typography;

const RegulationDetail: React.FC = () => {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<Regulation | null>(null);
  // [改进] 获取来源页面URL，用于返回按钮恢复原始状态
  const returnTo = (location.state as any)?.returnTo as string | undefined;

  const canEdit = hasPermission(user, PERM_REGULATION_EDIT);
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  // [新增] 历史版本详情弹窗
  const [historyDetail, setHistoryDetail] = useState<RegulationHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const showHistoryDetail = async (h: RegulationHistory) => {
    setHistoryLoading(true);
    try {
      const detail = await getRegulationHistoryDetail(Number(id), h.id);
      setHistoryDetail(detail);
    } catch { message.error('获取版本详情失败'); }
    finally { setHistoryLoading(false); }
  };

  useEffect(() => {
    if (id) {
      getRegulation(Number(id))
        .then((res) => setData(res))
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [id]);

  if (loading) return <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>;
  if (!data) return <div style={{ textAlign: 'center', padding: 48, color: '#999' }}>制度不存在</div>;

  return (
    <PageContainer maxWidth={960}>
      <PageHeader
        title="制度详情"
        onBack={() => navigate(returnTo || '/regulations')}
        extra={canEdit ? <Button type="primary" icon={<EditOutlined />} onClick={() => navigate(`/regulations/edit/${id}`, { state: { returnTo } })}>编辑</Button> : undefined}
      />

      {/* 基本信息 */}
      <Card title="基本信息" style={{ marginBottom: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2 }} size="small">
          <Descriptions.Item label="制度名称"><Text strong>{data.name}</Text></Descriptions.Item>
          <Descriptions.Item label="所属类别">
            {data.category_name ? <Tag color="blue">{data.category_name}</Tag> : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="制度版本">{data.version || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建人">{data.created_by || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{data.created_at ? formatDateTime(data.created_at) : '-'}</Descriptions.Item>
          <Descriptions.Item label="最后修改人">{data.updated_by || '-'}</Descriptions.Item>
          <Descriptions.Item label="最后修改时间">{data.updated_at ? formatDateTime(data.updated_at) : '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 制度内容 */}
      <Card title="制度内容" style={{ marginBottom: 16 }}>
        {data.content ? (
          <RichTextContent className="regulation-content" html={data.content} />
        ) : (
          <Text type="secondary">暂无内容</Text>
        )}
      </Card>

      {/* 修改历史 */}
      {data.history && data.history.length > 0 && (
        <Card title="历史版本" style={{ marginBottom: 16 }}>
          <Timeline
            items={data.history.map((h) => ({
              dot: <ClockCircleOutlined />,
              children: (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                    <Text strong>{h.version || '-'}</Text>
                    <Button size="small" type="link" icon={<EyeOutlined />} loading={historyLoading} onClick={() => showHistoryDetail(h)}>查看</Button>
                  </div>
                  {h.change_summary && <Text style={{ display: 'block' }}>{h.change_summary}</Text>}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {h.edited_by || '-'} · {h.edited_at ? formatDateTime(h.edited_at) : '-'}
                  </Text>
                </div>
              ),
            }))}
          />
        </Card>
      )}

      {/* 历史版本详情弹窗 */}
      <Modal
        open={!!historyDetail}
        title={`版本详情: ${historyDetail?.version || '-'}`}
        onCancel={() => setHistoryDetail(null)}
        footer={<Button onClick={() => setHistoryDetail(null)}>关闭</Button>}
        width={800}
      >
        {historyDetail && (
          <div style={{ maxHeight: '60vh', overflow: 'auto' }}>
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary">修改人: {historyDetail.edited_by || '-'}</Text>
              <br />
              <Text type="secondary">修改时间: {historyDetail.edited_at ? formatDateTime(historyDetail.edited_at) : '-'}</Text>
              {historyDetail.change_summary && (
                <>
                  <br />
                  <Text type="secondary">修改摘要: {historyDetail.change_summary}</Text>
                </>
              )}
            </div>
            <RichTextContent
              className="regulation-content"
              html={historyDetail.content || '暂无内容'}
              style={{ border: '1px solid #e5e7eb', borderRadius: 6, padding: 16, background: '#fafafa' }}
            />
          </div>
        )}
      </Modal>

      <style>{`
        .regulation-content img { max-width: 100%; height: auto; margin: 8px 0; }
        .regulation-content table { border-collapse: collapse; width: 100%; margin: 12px 0; }
        .regulation-content table td, .regulation-content table th { border: 1px solid #e5e7eb; padding: 8px 12px; }
        .regulation-content table th { background-color: #f9fafb; font-weight: 500; }
        .regulation-content p { margin: 8px 0; }
        .regulation-content h1,.regulation-content h2,.regulation-content h3,.regulation-content h4,.regulation-content h5,.regulation-content h6 { margin: 16px 0 8px; font-weight: 600; }
        .regulation-content ul,.regulation-content ol { margin: 8px 0; padding-left: 24px; }
        .regulation-content li { margin: 4px 0; }
      `}</style>
    </PageContainer>
  );
};

export default RegulationDetail;
