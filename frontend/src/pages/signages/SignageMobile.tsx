// [重构 2026-09-05] 原移动作业 → 标识巡检：
// ① 支持两种巡检方式：手动输入标识编号，或调用摄像头扫描二维码自动获取编号；
// ② 识别后提供标识状态选项（直接复用现有 status 字段取值）供选择并提交，
//    巡检结果同步写入标识的 status 字段；
// ③ 新增巡检历史查询：按时间范围、标识编号（可点击查看标识详情）、巡检人员筛选，
//    并可查看每次巡检的详细记录（巡检时间、标识状态、提交人等）。
import React, { useState, useEffect, useRef, useCallback } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Card, Tabs, Input, Button, Descriptions, Tag, Radio, Table, Modal,
  DatePicker, Space, Typography, AutoComplete,
} from 'antd';
import {
  SearchOutlined, ScanOutlined, QrcodeOutlined, HistoryOutlined, CameraOutlined, PictureOutlined,
} from '@ant-design/icons';
import { Link, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { Html5Qrcode } from 'html5-qrcode';
import {
  getSignageByCode, createSignageInspection, getSignageInspections, getSignageList, uploadInspectionPhoto,
} from '../../api/signage';
import { compressImageFile } from '../../utils/imageUtils';
import { formatDateTimeStandard } from '../../utils/time';
import type { Signage, SignageInspectionRecord } from '../../api/signage';
import { SIGNAGE_STATUS_OPTIONS, SIGNAGE_STATUS_MAP } from '../../constants/signageStatus';

const { Text } = Typography;
const { RangePicker } = DatePicker;

const SignageMobile: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  // ===== 巡检打卡 =====
  const [code, setCode] = useState('');
  const [signage, setSignage] = useState<Signage | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [result, setResult] = useState<string>();
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [scanning, setScanning] = useState(false);
  const scannerRef = useRef<Html5Qrcode | null>(null);

  // [新增 2026-09-07] 巡检打卡输入框模糊联想：输入关键词时展示相似匹配结果供选择
  const [codeOptions, setCodeOptions] = useState<{ value: string; label: React.ReactNode }[]>([]);
  const codeSearchTimer = useRef<number | null>(null);

  // [新增 2026-09-07] 提交巡检时的拍照/上传照片弹窗与压缩后照片状态
  const [photoModalVisible, setPhotoModalVisible] = useState(false);
  const [photoFile, setPhotoFile] = useState<File | null>(null); // 压缩后的照片（不保留原始文件）
  const [photoPreview, setPhotoPreview] = useState<string | null>(null); // 压缩后照片的本地预览
  const [compressing, setCompressing] = useState(false);
  const cameraInputRef = useRef<HTMLInputElement | null>(null);
  const galleryInputRef = useRef<HTMLInputElement | null>(null);

  // [新增 2026-09-07] 预览 URL 生命周期管理：切换/卸载时自动释放，避免内存泄漏
  useEffect(() => () => {
    if (photoPreview) URL.revokeObjectURL(photoPreview);
  }, [photoPreview]);

  const handleCodeSearch = (kw: string) => {
    const v = kw.trim();
    if (codeSearchTimer.current) window.clearTimeout(codeSearchTimer.current);
    if (!v) { setCodeOptions([]); return; }
    codeSearchTimer.current = window.setTimeout(async () => {
      try {
        const r = await getSignageList({ search: v, page_size: 10 });
        setCodeOptions(
          r.items.map((s) => ({
            value: s.code,
            label: (
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
                <span style={{ fontWeight: 600 }}>{s.code}</span>
                <span style={{ color: 'var(--text-3)', fontSize: 12 }}>
                  {s.name}{[s.campus, s.building].filter(Boolean).join(' / ')}
                </span>
              </div>
            ),
          })),
        );
      } catch {
        setCodeOptions([]);
      }
    }, 300);
  };

  // ===== 巡检历史 =====
  const [history, setHistory] = useState<SignageInspectionRecord[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [fCode, setFCode] = useState('');
  const [fInspector, setFInspector] = useState('');
  const [fRange, setFRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [detail, setDetail] = useState<SignageInspectionRecord | null>(null);
  const [activeTab, setActiveTab] = useState('checkin');

  // ===== 巡检历史查询 =====
  const loadHistory = useCallback(async (page = 1) => {
    setHistoryLoading(true);
    setHistoryPage(page);
    try {
      const r = await getSignageInspections({
        page,
        page_size: 10,
        code: fCode.trim() || undefined,
        inspector: fInspector.trim() || undefined,
        start_date: fRange?.[0]?.format('YYYY-MM-DD'),
        end_date: fRange?.[1]?.format('YYYY-MM-DD'),
      });
      setHistory(r.items);
      setHistoryTotal(r.total);
    } catch {
      message.error('获取巡检历史失败');
    } finally {
      setHistoryLoading(false);
    }
  }, [fCode, fInspector, fRange]);

  // [修复 2026-09-08] 兼容二维码内容：新码只编码纯编号；旧码编码了
  // “标识编码：XXX / 院区： / 位置：”整段文本。这里统一提取出纯编号再去匹配。
  const normalizeScannedCode = (raw?: string): string => {
    const text = (raw ?? '').trim();
    if (!text) return text;
    const m = text.match(/标识编码[:：]\s*(.+)/);
    if (m) return m[1].split(/\r?\n/)[0].trim();
    return text;
  };

  // 按编号查询标识（手输或扫码结果共用）
  const handleLookup = useCallback(async (raw?: string) => {
    const c = normalizeScannedCode(raw ?? code).trim();
    if (!c) { message.warning('请输入标识编号'); return; }
    setLookupLoading(true);
    setResult(undefined);
    setNotes('');
    try {
      const data = await getSignageByCode(c);
      setSignage(data);
    } catch (e: any) {
      setSignage(null);
      message.error(e?.response?.data?.detail || '未找到该编号的标识');
    } finally {
      setLookupLoading(false);
    }
  }, [code]);

  // ===== 摄像头扫码（html5-qrcode）=====
  // [修复 2026-09-08] 摄像头无法打开的根因：Html5Qrcode 构造函数要求 #qr-reader
  // 元素必须先存在于 DOM，否则直接抛 "not found" 被 catch 后误报"无法打开摄像头"。
  // 改为由 scanning 状态触发 useEffect，确保元素渲染完成后再构造并启动；
  // 同时新增：安全上下文校验、摄像头枚举（优先后置、回退任意）、按错误类型提示。
  const stopScan = useCallback(async () => {
    const s = scannerRef.current;
    if (s) {
      try { await s.stop(); s.clear(); } catch { /* 已停止则忽略 */ }
    }
    scannerRef.current = null;
    setScanning(false);
  }, []);

  // 用 ref 持有最新 handleLookup，避免其变化（依赖 code）导致扫码 effect 重复重启
  const handleLookupRef = useRef(handleLookup);
  useEffect(() => { handleLookupRef.current = handleLookup; }, [handleLookup]);

  // [新增 2026-09-08] 支持预警页「立即巡检」跳转预填：/signage-mobile?code=XXX 自动查询该标识
  const [searchParams] = useSearchParams();
  const prefillApplied = useRef(false);
  useEffect(() => {
    const prefillCode = searchParams.get('code');
    if (prefillCode && !prefillApplied.current) {
      prefillApplied.current = true;
      setCode(prefillCode);
      handleLookupRef.current(prefillCode);
    }
  }, [searchParams]);

  useEffect(() => {
    if (!scanning) return;
    let cancelled = false;
    (async () => {
      // 前置校验：getUserMedia 仅在安全上下文（HTTPS / localhost）可用
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        message.error('摄像头需在 HTTPS 安全环境（或 localhost）下使用，请确认访问地址为 https:// 开头');
        setScanning(false);
        return;
      }
      try {
        const scanner = new Html5Qrcode('qr-reader'); // 此时 #qr-reader 已挂载
        scannerRef.current = scanner;

        // 枚举摄像头：优先后置，否则回退到首个可用摄像头，避免 facingMode 受限报错
        let cameraId: string | undefined;
        try {
          const cams = await Html5Qrcode.getCameras();
          if (cams && cams.length) {
            const env = cams.find((c) => /back|rear|environment|后置/i.test(c.label));
            cameraId = (env ?? cams[0]).id;
          }
        } catch { /* 枚举失败则回落到 constraints 方式 */ }

        await scanner.start(
          cameraId ?? { facingMode: 'environment' },
          { fps: 10, qrbox: { width: 220, height: 220 } },
          (decodedText: string) => {
            if (cancelled) return;
            stopScan();
            const c = normalizeScannedCode(decodedText);
            setCode(c);
            message.success(`已识别编号：${c}`);
            handleLookupRef.current(c);
          },
          () => { /* 每帧未识别到二维码属正常情况，忽略 */ },
        );
      } catch (err: any) {
        const name = err?.name || '';
        if (name === 'NotAllowedError' || name === 'SecurityError') {
          message.error('摄像头权限被拒绝，请在浏览器地址栏允许摄像头权限后重试');
        } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
          message.error('未检测到可用摄像头，请改用手动输入标识编号');
        } else {
          message.error('无法打开摄像头，请检查摄像头权限或改用手动输入');
        }
        setScanning(false);
      }
    })();
    return () => { cancelled = true; };
  }, [scanning, stopScan]);

  // 卸载时释放摄像头
  useEffect(() => () => { stopScan(); }, [stopScan]);

  // [修复 2026-09-07] 点击"提交巡检"先做基础校验，再弹出拍照/上传照片选项弹窗
  const openPhotoModal = () => {
    if (!signage) { message.warning('请先查询标识'); return; }
    if (!result) { message.warning('请选择标识状态'); return; }
    setPhotoModalVisible(true);
  };

  // [新增 2026-09-07] 选择照片（拍照/相册共用）：客户端压缩后保存，不保留原始文件
  const handlePhotoSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // 允许重复选择同一文件
    if (!file) return;
    setCompressing(true);
    try {
      const compressed = await compressImageFile(file);
      setPhotoFile(compressed);
      setPhotoPreview(URL.createObjectURL(compressed));
      message.success(`照片已压缩：${(file.size / 1024).toFixed(0)}KB → ${(compressed.size / 1024).toFixed(0)}KB（分辨率不变）`);
    } catch {
      message.error('照片处理失败，请重试');
    } finally {
      setCompressing(false);
    }
  };

  // [新增 2026-09-07] 移除已选照片（选择不上传照片）
  const clearPhoto = () => {
    setPhotoFile(null);
    setPhotoPreview(null);
  };

  // 提交巡检（[修复 2026-09-07] 支持可选现场照片：先上传压缩后照片获取路径，再随巡检结果提交；不上传则直接提交）
  const handleSubmit = async () => {
    if (!signage) { message.warning('请先查询标识'); return; }
    if (!result) { message.warning('请选择标识状态'); return; }
    setSubmitting(true);
    try {
      let photoPath: string | undefined;
      if (photoFile) {
        const r = await uploadInspectionPhoto(signage.code, photoFile);
        photoPath = r.file_path;
      }
      // [新增 2026-09-08] 兼容越权科室巡检：后端返回 warning 时不记录巡检，仅提示用户
      const resp: any = await createSignageInspection({ code: signage.code, result, notes: notes.trim() || undefined, photo: photoPath });
      if (resp && resp.ok === false && resp.warning) {
        message.warning(resp.message);
        setSubmitting(false);
        return;
      }
      message.success('巡检提交成功，标识状态已更新');
      setSignage({ ...signage, status: result });
      setResult(undefined);
      setNotes('');
      clearPhoto();
      setPhotoModalVisible(false);
      if (activeTab === 'history') loadHistory(historyPage);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '巡检提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  // 切换页签：释放摄像头；进入历史页签时加载记录
  const handleTabChange = (key: string) => {
    stopScan();
    setActiveTab(key);
    if (key === 'history') loadHistory(1);
  };

  const historyColumns = [
    {
      title: '巡检时间', dataIndex: 'created_at', key: 'created_at', width: 160,
      // [修复 2026-09-08] 后端时间为 UTC，改用 time 工具按本地时区转换（原样显示会差 8 小时）
      render: (t: string) => formatDateTimeStandard(t),
    },
    {
      title: '标识编号', dataIndex: 'signage_code', key: 'signage_code', width: 170,
      render: (code: string, r: SignageInspectionRecord) => (
        <Link to={`/signages/${r.signage_id}`}>
          <Button type="link" size="small" style={{ padding: 0 }}>{code || '-'}</Button>
        </Link>
      ),
    },
    { title: '标识名称', dataIndex: 'signage_name', key: 'signage_name', ellipsis: true },
    {
      title: '巡检状态', dataIndex: 'result', key: 'result', width: 100,
      render: (v: string) => {
        const m = SIGNAGE_STATUS_MAP[v];
        return <Tag color={m?.color || 'default'}>{m?.label || v}</Tag>;
      },
    },
    { title: '提交人', dataIndex: 'inspector', key: 'inspector', width: 100 },
    { title: '备注', dataIndex: 'notes', key: 'notes', ellipsis: true, render: (t?: string) => t || '-' },
    {
      title: '操作', key: 'action', width: 70,
      render: (_: any, r: SignageInspectionRecord) => (
        <Button type="link" size="small" onClick={() => setDetail(r)}>详情</Button>
      ),
    },
  ];

  const checkinNode = (
    <>
      <Card title="第一步：获取标识编号" style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
          <AutoComplete
            id="inspection-code"
            style={{ flex: 1 }}
            placeholder="手动输入标识编号（支持编号/名称模糊搜索）"
            value={code}
            options={codeOptions}
            onSearch={handleCodeSearch}
            onChange={(v) => setCode(v)}
            onSelect={(v) => { setCode(v); handleLookup(v); }}
            // [修复 2026-09-08] AutoComplete 类型上不存在 onPressEnter，改用 onInputKeyDown 监听回车查询
            onInputKeyDown={(e) => { if (e.key === 'Enter') handleLookup(); }}
            allowClear
            notFoundContent={code ? '无匹配标识' : null}
          />
          <Button type="primary" icon={<SearchOutlined />} loading={lookupLoading} onClick={() => handleLookup()}>
            查询
          </Button>
        </Space.Compact>
        <Button
          icon={scanning ? <CameraOutlined /> : <QrcodeOutlined />}
          onClick={scanning ? stopScan : () => setScanning(true)}
          block
          danger={scanning}
        >
          {scanning ? '关闭摄像头' : '扫描二维码自动获取编号'}
        </Button>
        {/* 扫码区域：容器必须在 scanner.start 之前存在于 DOM */}
        {scanning && <div id="qr-reader" style={{ marginTop: 12, borderRadius: 8, overflow: 'hidden' }} />}
        <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
          支持两种巡检方式：手动输入标识编号，或调用摄像头扫描标识二维码自动获取编号
        </Text>
      </Card>

      {signage && (
        <>
          <Card title="标识信息" style={{ marginBottom: 16 }}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="编码">{signage.code}</Descriptions.Item>
              <Descriptions.Item label="名称">{signage.name}</Descriptions.Item>
              <Descriptions.Item label="分类">{signage.category}</Descriptions.Item>
              <Descriptions.Item label="当前状态">
                <Tag color={SIGNAGE_STATUS_MAP[signage.status]?.color}>
                  {SIGNAGE_STATUS_MAP[signage.status]?.label || signage.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="位置">
                {[signage.campus, signage.building, signage.floor].filter(Boolean).join(' / ') || '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
          <Card title="第二步：提交巡检结果" style={{ marginBottom: 16 }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              选择标识状态（选项来自现有状态字段）：
            </Text>
            <Radio.Group
              value={result}
              onChange={(e) => setResult(e.target.value)}
              style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}
            >
              {SIGNAGE_STATUS_OPTIONS.map((s) => (
                <Radio key={s.value} value={s.value}>
                  <Tag color={s.color}>{s.label}</Tag>
                </Radio>
              ))}
            </Radio.Group>
            <Input.TextArea
              placeholder="巡检备注（选填）"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{ marginBottom: 12 }}
            />
            {/* [修复 2026-09-07] 点击提交先弹出拍照/上传照片选项（可跳过照片直接提交） */}
            <Button type="primary" block onClick={openPhotoModal}>
              提交巡检
            </Button>
          </Card>

          {/* [新增 2026-09-07] 拍照/上传照片弹窗：可选照片，不上传也可直接提交 */}
          <Modal
            title="现场照片（可选）"
            open={photoModalVisible}
            onCancel={() => setPhotoModalVisible(false)}
            footer={null}
            destroyOnHidden
          >
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              可拍照或上传现场照片（将自动压缩以节省流量与存储，分辨率保持不变）；也可不上传照片直接提交。
            </Text>
            {photoPreview ? (
              <>
                <img
                  src={photoPreview}
                  alt="巡检照片预览"
                  style={{ width: '100%', maxHeight: 280, objectFit: 'contain', borderRadius: 8, background: 'var(--line-softer)' }}
                />
                <Space direction="vertical" style={{ width: '100%', marginTop: 12 }} size={8}>
                  <Button block icon={<CameraOutlined />} disabled={compressing} onClick={() => cameraInputRef.current?.click()}>
                    重新拍照
                  </Button>
                  <Button block icon={<PictureOutlined />} disabled={compressing} onClick={() => galleryInputRef.current?.click()}>
                    重新选择图片
                  </Button>
                  <Button type="primary" block loading={submitting || compressing} onClick={handleSubmit}>
                    确认提交
                  </Button>
                  <Button block type="text" danger onClick={clearPhoto}>
                    移除照片，不上传
                  </Button>
                </Space>
              </>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                <Button block size="large" icon={<CameraOutlined />} loading={compressing} onClick={() => cameraInputRef.current?.click()}>
                  拍照
                </Button>
                <Button block size="large" icon={<PictureOutlined />} loading={compressing} onClick={() => galleryInputRef.current?.click()}>
                  上传照片
                </Button>
                <Button block size="large" type="primary" loading={submitting} onClick={handleSubmit}>
                  不上传照片，直接提交
                </Button>
              </Space>
            )}
            {/* 隐藏的文件选择控件：capture 触发系统相机，另一入口选择相册/文件 */}
            <input
              ref={cameraInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              style={{ display: 'none' }}
              onChange={handlePhotoSelected}
            />
            <input
              ref={galleryInputRef}
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={handlePhotoSelected}
            />
          </Modal>
        </>
      )}
    </>
  );

  const historyNode = (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <RangePicker
            style={{ width: '100%' }}
            value={fRange}
            onChange={(v) => setFRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null)}
            placeholder={['开始日期', '结束日期']}
          />
          <Space.Compact style={{ width: '100%' }}>
            <Input
              id="inspection-history-code"
              placeholder="标识编号"
              value={fCode}
              onChange={(e) => setFCode(e.target.value)}
              onPressEnter={() => loadHistory(1)}
              allowClear
            />
            <Input
              id="inspection-history-inspector"
              placeholder="巡检人员"
              value={fInspector}
              onChange={(e) => setFInspector(e.target.value)}
              onPressEnter={() => loadHistory(1)}
              allowClear
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadHistory(1)}>
              查询
            </Button>
          </Space.Compact>
          <Button
            block
            onClick={() => { setFCode(''); setFInspector(''); setFRange(null); loadHistory(1); }}
          >
            重置筛选
          </Button>
        </Space>
      </Card>
      <Card title={`巡检记录（共 ${historyTotal} 条）`}>
        <Table
          rowKey="id"
          size="small"
          loading={historyLoading}
          dataSource={history}
          columns={historyColumns}
          pagination={{
            current: historyPage,
            pageSize: 10,
            total: historyTotal,
            showSizeChanger: false,
            onChange: (p) => loadHistory(p),
            showTotal: (t) => `共 ${t} 条`,
          }}
        />
      </Card>
    </>
  );

  return (
    <div style={{ maxWidth: 600, margin: '0 auto', padding: 16 }}>
      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        items={[
          { key: 'checkin', label: (<><ScanOutlined /> 巡检打卡</>), children: checkinNode },
          { key: 'history', label: (<><HistoryOutlined /> 巡检历史</>), children: historyNode },
        ]}
      />

      {/* 巡检详情模态框 */}
      <Modal
        title="巡检记录详情"
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={<Button onClick={() => setDetail(null)}>关闭</Button>}
        width={520}
      >
        {detail && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="巡检时间">
              {/* [修复 2026-09-08] UTC 时间按本地时区转换显示 */}
              {formatDateTimeStandard(detail.created_at)}
            </Descriptions.Item>
            <Descriptions.Item label="标识编号">
              <Link to={`/signages/${detail.signage_id}`}>{detail.signage_code || '-'}</Link>
            </Descriptions.Item>
            <Descriptions.Item label="标识名称">{detail.signage_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="巡检状态">
              <Tag color={SIGNAGE_STATUS_MAP[detail.result]?.color}>
                {SIGNAGE_STATUS_MAP[detail.result]?.label || detail.result}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="标识当前状态">
              <Tag color={SIGNAGE_STATUS_MAP[detail.signage_status || '']?.color}>
                {SIGNAGE_STATUS_MAP[detail.signage_status || '']?.label || detail.signage_status || '-'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="提交人">{detail.inspector || '-'}</Descriptions.Item>
            <Descriptions.Item label="备注">{detail.notes || '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
};

export default SignageMobile;
