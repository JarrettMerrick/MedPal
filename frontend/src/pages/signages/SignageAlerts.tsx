// [重构 2026-09-05] 标识预警页：
// - 删除「质保即将到期」「已过质保期」两张卡片
// - 新增「状态异常标识」卡片（轻微破损/严重损坏）
// - 巡检预警按分类巡检周期计算，分为「7天内巡检到期」「巡检已超期」
// - 「临时标识即将过期」改为基于新增的有效期字段（validity_until）
// [新增 2026-09-08] 预警处理功能：
// - 巡检临期（7天内到期/已超期）：提供「立即巡检」按钮，跳转巡检页并预填标识编码
// - 状态异常（轻微破损/严重损坏）：提供「标识维修」按钮，选择维修方发起维修
//   （供应商维修：OA单号可选+供应商必选；工程部维修：可直接确认）→ 预警状态变更为「维修处理中」
// - 维修处理中：提供「完成维修」按钮，可选上传维修完成照片（上传后替换标识详情页安装现场照片），
//   完成后预警状态自动变更为「正常」
import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Statistic, Row, Col, Table, Tag, message, Typography, Button, Modal,
  Radio, Input, Select, Space,
} from 'antd';
import {
  AlertOutlined, WarningOutlined, ClockCircleOutlined, FieldTimeOutlined,
  ToolOutlined, CheckCircleOutlined, PictureOutlined,
} from '@ant-design/icons';
import { Link, useNavigate } from 'react-router-dom';
import api from '../../api/client';
import { SIGNAGE_STATUS_MAP } from '../../constants/signageStatus';
import { getActiveSuppliers } from '../../api/signage-settings';
import type { Supplier } from '../../api/signage-settings';
import { startSignageRepair, completeSignageRepair, uploadRepairPhoto } from '../../api/signage';
import { compressImageFile } from '../../utils/imageUtils';

const { Text } = Typography;

interface AlertItem {
  id: number;
  code: string;
  name: string;
  // 状态异常
  status?: string;
  // 维修处理中（id 为维修记录 id；signage_id 用于跳转标识详情）
  signage_id?: number;
  repair_party?: string;
  supplier_name?: string;
  oa_number?: string;
  started_at?: string;
  // 巡检类
  category?: string;
  cycle_days?: number;
  last_inspection_date?: string;
  due_date?: string;
  days_left?: number;
  days_overdue?: number;
  // 临时标识有效期
  validity_until?: string;
}

interface AlertSummary {
  abnormal_status: number;
  inspection_due_soon: number;
  inspection_overdue: number;
  temporary_expiring: number;
  repair_in_progress: number;
  total: number;
  details: {
    abnormal_status: AlertItem[];
    inspection_due_soon: AlertItem[];
    inspection_overdue: AlertItem[];
    temporary_expiring: AlertItem[];
    repair_in_progress: AlertItem[];
  };
}

type AlertRow = AlertItem & { type: string };

const SignageAlerts: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<AlertSummary | null>(null);
  const navigate = useNavigate();

  // ===== [新增 2026-09-08] 发起维修（状态异常 → 维修处理中） =====
  const [repairTarget, setRepairTarget] = useState<AlertRow | null>(null);
  const [repairParty, setRepairParty] = useState<'vendor' | 'engineering'>('engineering');
  const [oaNumber, setOaNumber] = useState('');
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [repairSubmitting, setRepairSubmitting] = useState(false);

  // ===== [新增 2026-09-08] 完成维修（维修处理中 → 正常，可选上传照片） =====
  const [completeTarget, setCompleteTarget] = useState<AlertRow | null>(null);
  const [repairPhotoPreview, setRepairPhotoPreview] = useState<string | null>(null);
  const [repairPhotoPath, setRepairPhotoPath] = useState<string | undefined>(undefined);
  const [repairPhotoUploading, setRepairPhotoUploading] = useState(false);
  const [completeSubmitting, setCompleteSubmitting] = useState(false);
  const repairPhotoInputRef = useRef<HTMLInputElement | null>(null);

  const loadAlerts = useCallback(() => {
    setLoading(true);
    api.get('/signage-alerts/summary').then((r) => setData(r.data))
      .catch(() => message.error('获取预警失败')).finally(() => setLoading(false));
  }, []);

  useEffect(() => { loadAlerts(); }, [loadAlerts]);

  // [新增 2026-09-08] 加载供应商列表（供应商维修下拉，取供应商设置中启用的制作厂商）
  useEffect(() => {
    getActiveSuppliers().then(setSuppliers).catch(() => setSuppliers([]));
  }, []);

  // 预览 URL 生命周期：卸载时释放
  useEffect(() => () => {
    if (repairPhotoPreview) URL.revokeObjectURL(repairPhotoPreview);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ----- 发起维修 -----
  const openRepairModal = (r: AlertRow) => {
    setRepairTarget(r);
    setRepairParty('engineering');
    setOaNumber('');
    setSupplierId(undefined);
  };

  const handleStartRepair = async () => {
    if (!repairTarget) return;
    if (repairParty === 'vendor' && !supplierId) {
      message.warning('选择供应商维修时必须选择供应商');
      return;
    }
    setRepairSubmitting(true);
    try {
      await startSignageRepair({
        signage_id: repairTarget.id,
        repair_party: repairParty,
        oa_number: repairParty === 'vendor' && oaNumber.trim() ? oaNumber.trim() : undefined,
        supplier_id: repairParty === 'vendor' ? supplierId : undefined,
      });
      message.success('已发起维修，预警状态变更为「维修处理中」');
      setRepairTarget(null);
      loadAlerts();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '发起维修失败');
    } finally {
      setRepairSubmitting(false);
    }
  };

  // ----- 完成维修 -----
  const openCompleteModal = (r: AlertRow) => {
    setCompleteTarget(r);
    setRepairPhotoPreview(null);
    setRepairPhotoPath(undefined);
  };

  const closeCompleteModal = () => {
    if (repairPhotoPreview) URL.revokeObjectURL(repairPhotoPreview);
    setCompleteTarget(null);
    setRepairPhotoPreview(null);
    setRepairPhotoPath(undefined);
  };

  // 选择维修完成照片：客户端压缩后立即上传，保留路径用于完成维修提交
  const handleRepairPhotoSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // 允许重复选择同一文件
    if (!file) return;
    setRepairPhotoUploading(true);
    try {
      const compressed = await compressImageFile(file);
      if (repairPhotoPreview) URL.revokeObjectURL(repairPhotoPreview);
      setRepairPhotoPreview(URL.createObjectURL(compressed));
      const r = await uploadRepairPhoto(compressed);
      setRepairPhotoPath(r.file_path);
      message.success('维修完成照片已上传');
    } catch {
      message.error('照片上传失败，请重试');
    } finally {
      setRepairPhotoUploading(false);
    }
  };

  const clearRepairPhoto = () => {
    if (repairPhotoPreview) URL.revokeObjectURL(repairPhotoPreview);
    setRepairPhotoPreview(null);
    setRepairPhotoPath(undefined);
  };

  const handleCompleteRepair = async () => {
    if (!completeTarget) return;
    setCompleteSubmitting(true);
    try {
      await completeSignageRepair(completeTarget.id, repairPhotoPath);
      message.success('维修已完成，预警状态变更为「正常」');
      closeCompleteModal();
      loadAlerts();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '完成维修失败');
    } finally {
      setCompleteSubmitting(false);
    }
  };

  if (!data) return <Card loading={loading} />;

  // [重构 2026-09-05] 预警类型：状态异常 / 维修处理中 / 7天内巡检到期 / 巡检已超期 / 临时标识有效期提醒
  // [调整 2026-09-14] 末项由「临时标识即将过期」改名为「临时标识有效期提醒」：
  //   该列表口径为 validity_until <= 今天+7，**同时包含已过期项**，
  //   原名对早已过期的标识描述不准确（详见后端 signage_alert_service）。
  const alertData: AlertRow[] = [
    ...data.details.abnormal_status.map((i) => ({ ...i, type: '状态异常' })),
    ...data.details.repair_in_progress.map((i) => ({ ...i, type: '维修处理中' })),
    ...data.details.inspection_due_soon.map((i) => ({ ...i, type: '7天内巡检到期' })),
    ...data.details.inspection_overdue.map((i) => ({ ...i, type: '巡检已超期' })),
    ...data.details.temporary_expiring.map((i) => ({ ...i, type: '临时标识有效期提醒' })),
  ];

  const typeColor = (t: string) => {
    if (t === '状态异常' || t === '巡检已超期') return 'red';
    if (t === '维修处理中') return 'processing';
    if (t === '临时标识有效期提醒') return 'volcano';
    return 'orange';
  };

  const infoRender = (_: unknown, r: AlertRow) => {
    if (r.type === '状态异常') {
      const m = SIGNAGE_STATUS_MAP[r.status || ''];
      return <Tag color={m?.color || 'default'}>{m?.label || r.status}</Tag>;
    }
    if (r.type === '维修处理中') {
      const party = r.repair_party === 'vendor'
        ? `供应商维修${r.supplier_name ? `（${r.supplier_name}）` : ''}`
        : '工程部维修';
      return (
        <Text type="secondary">
          {party}{r.oa_number ? ` · OA单号 ${r.oa_number}` : ''}{r.started_at ? ` · 发起于 ${r.started_at}` : ''}
        </Text>
      );
    }
    if (r.type === '7天内巡检到期') {
      return <Text type="warning">{r.days_left} 天后到期（{r.due_date}）</Text>;
    }
    if (r.type === '巡检已超期') {
      return <Text type="danger">已超期 {r.days_overdue} 天（应检日 {r.due_date}）</Text>;
    }
    if (r.type === '临时标识有效期提醒') {
      // [新增 2026-09-14] 区分「临期」与「已过期」：days_left 为负表示已过期天数
      if (r.days_left === undefined || r.days_left === null) return r.validity_until || '-';
      return r.days_left < 0
        ? <Text type="danger">已过期 {Math.abs(r.days_left)} 天（有效期至 {r.validity_until}）</Text>
        : <Text type="warning">{r.days_left} 天后过期（{r.validity_until}）</Text>;
    }
    return r.validity_until || '-';
  };

  // [新增 2026-09-08] 操作列：巡检临期→立即巡检；状态异常→标识维修；维修处理中→完成维修
  const actionRender = (_: unknown, r: AlertRow) => {
    if (r.type === '状态异常') {
      return (
        <Button size="small" type="primary" icon={<ToolOutlined />} onClick={() => openRepairModal(r)}>
          标识维修
        </Button>
      );
    }
    if (r.type === '维修处理中') {
      return (
        <Button size="small" icon={<CheckCircleOutlined />} onClick={() => openCompleteModal(r)}>
          完成维修
        </Button>
      );
    }
    if (r.type === '7天内巡检到期' || r.type === '巡检已超期') {
      return (
        <Button
          size="small"
          type="primary"
          ghost
          onClick={() => navigate(`/signage-mobile?code=${encodeURIComponent(r.code)}`)}
        >
          立即巡检
        </Button>
      );
    }
    return null;
  };

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="状态异常标识" value={data.abnormal_status} prefix={<WarningOutlined />} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="维修处理中" value={data.repair_in_progress} prefix={<ToolOutlined />} valueStyle={{ color: '#1677ff' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="7天内巡检到期" value={data.inspection_due_soon} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#faad14' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="巡检已超期" value={data.inspection_overdue} prefix={<AlertOutlined />} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card><Statistic title="临时标识有效期提醒" value={data.temporary_expiring} prefix={<FieldTimeOutlined />} valueStyle={{ color: '#fa8c16' }} /></Card></Col>
        <Col span={16}>
          <Card>
            <Text type="secondary">
              巡检到期/超期依据「标识分类」中配置的巡检周期计算；未配置周期的分类不参与巡检预警。
              状态异常标识可发起维修（供应商/工程部），维修完成后预警自动消除。
            </Text>
          </Card>
        </Col>
      </Row>
      <Card title="预警详情" loading={loading}>
        <Table<AlertRow>
          dataSource={alertData}
          rowKey={(r) => `${r.type}-${r.id}`}
          columns={[
            { title: '类型', dataIndex: 'type', key: 'type', width: 140, render: (v: string) => <Tag color={typeColor(v)}>{v}</Tag> },
            {
              title: '编码', dataIndex: 'code', key: 'code', width: 180,
              // [修复 2026-09-09] 行类型标注为 AlertRow（含 type 字段），修复 tsc 报错 Property 'type' does not exist
              render: (code: string, r: AlertRow) => (
                <Link to={`/signages/${r.type === '维修处理中' ? r.signage_id ?? r.id : r.id}`}>{code}</Link>
              ),
            },
            { title: '名称', dataIndex: 'name', key: 'name' },
            { title: '分类', dataIndex: 'category', key: 'category', width: 110, render: (v?: string) => v || '-' },
            { title: '说明', key: 'info', render: infoRender },
            { title: '操作', key: 'actions', width: 130, render: actionRender },
          ]}
          pagination={{ pageSize: 10 }}
        />
      </Card>

      {/* [新增 2026-09-08] 发起维修弹窗：选择维修方；供应商维修需选供应商（OA单号可选） */}
      <Modal
        title={`标识维修 - ${repairTarget?.name || ''}（${repairTarget?.code || ''}）`}
        open={!!repairTarget}
        onCancel={() => setRepairTarget(null)}
        onOk={handleStartRepair}
        confirmLoading={repairSubmitting}
        okText="确认"
        cancelText="取消"
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <div>
            <Text strong style={{ display: 'block', marginBottom: 8 }}>维修方</Text>
            <Radio.Group value={repairParty} onChange={(e) => setRepairParty(e.target.value)}>
              <Radio.Button value="vendor">供应商维修</Radio.Button>
              <Radio.Button value="engineering">工程部维修</Radio.Button>
            </Radio.Group>
          </div>
          {repairParty === 'vendor' && (
            <>
              <div>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  OA 单号 <Text type="secondary">（可选）</Text>
                </Text>
                <Input
                  placeholder="请输入 OA 单号"
                  value={oaNumber}
                  onChange={(e) => setOaNumber(e.target.value)}
                  allowClear
                />
              </div>
              <div>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  供应商 <Text type="danger">*</Text>
                </Text>
                <Select
                  placeholder="请选择供应商（制作厂商）"
                  style={{ width: '100%' }}
                  showSearch
                  optionFilterProp="label"
                  value={supplierId}
                  onChange={(v) => setSupplierId(v)}
                  options={suppliers.map((s) => ({ value: s.id, label: s.name }))}
                />
              </div>
            </>
          )}
          {repairParty === 'engineering' && (
            <Text type="secondary">工程部维修可直接确认，预警状态将变更为「维修处理中」。</Text>
          )}
        </Space>
      </Modal>

      {/* [新增 2026-09-08] 完成维修弹窗：可选上传维修完成照片（上传后替换标识安装现场照片） */}
      <Modal
        title={`完成维修 - ${completeTarget?.name || ''}（${completeTarget?.code || ''}）`}
        open={!!completeTarget}
        onCancel={closeCompleteModal}
        onOk={handleCompleteRepair}
        confirmLoading={completeSubmitting || repairPhotoUploading}
        okText="确认完成"
        cancelText="取消"
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Text type="secondary">
            确认后预警状态自动变更为「正常」；可选择性上传维修完成照片，上传后将替换标识详情页的安装现场照片。
          </Text>
          {repairPhotoPreview ? (
            <>
              <img
                src={repairPhotoPreview}
                alt="维修完成照片预览"
                style={{ width: '100%', maxHeight: 260, objectFit: 'contain', borderRadius: 8, background: '#f5f5f5' }}
              />
              <Space>
                <Button icon={<PictureOutlined />} disabled={repairPhotoUploading} onClick={() => repairPhotoInputRef.current?.click()}>
                  重新选择
                </Button>
                <Button type="text" danger onClick={clearRepairPhoto}>移除照片</Button>
              </Space>
            </>
          ) : (
            <Button block icon={<PictureOutlined />} loading={repairPhotoUploading} onClick={() => repairPhotoInputRef.current?.click()}>
              上传维修完成照片（可选）
            </Button>
          )}
          <input
            ref={repairPhotoInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={handleRepairPhotoSelected}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default SignageAlerts;
