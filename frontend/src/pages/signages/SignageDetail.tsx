// [修复 2026-09-04] 按照参考设计稿重写标识详情展示页
// 顶栏返回+标题+状态标签+编辑按钮，Hero区域大图+信息卡片，双栏位置+安装信息，附件资料，灯箱预览
// [修复 2026-09-04] 新增历史版本快照查看功能
import React, { useState, useEffect, useRef } from 'react';
import { Button, message, Spin, Empty, Tag, Modal, Timeline, Descriptions, Typography, Divider, List, Card, Tooltip } from 'antd';
import { EditOutlined, ArrowLeftOutlined, DownloadOutlined, EyeOutlined, FileOutlined, HistoryOutlined, ClockCircleOutlined, FileSearchOutlined, ToolOutlined, SyncOutlined, CopyOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { getSignage, getSignagePhotos, getSignageHistory, getSignageInspections, getSignageRepairs } from '../../api/signage';
import type { Signage, SignagePhoto, SignageHistory, SignageInspectionRecord, SignageRepairRecord } from '../../api/signage';
// [调整 2026-09-15] 补充导入 PERM_SIGNAGE_REPAIR（维修记录）与 PERM_SIGNAGE_INSPECTION（巡检历史），
// 用于详情页顶部「维修记录/巡检历史/查看历史版本」三个按钮的独立权限门禁（无权限直接隐藏）
import { hasPermission, PERM_SIGNAGE_EDIT, PERM_SIGNAGE_INSPECTION, PERM_SIGNAGE_REPAIR } from '../../utils/permissions';
// [新增 2026-09-09] 历史版本字段名与枚举值中文翻译（B1）
import { signageFieldLabel, formatSignageFieldValue } from '../../constants/signageFields';
import { useAuth } from '../../contexts/AuthContext';
import { getOriginalUrl } from '../../utils/imageUtils';
import { formatDateTimeStandard } from '../../utils/time';
// [新增 2026-09-14] 剪贴板复制（兼容院内网 http 访问环境）
import { copyText } from '../../utils/clipboard';
import { QRCodeCanvas } from 'qrcode.react';

// [修复 2026-09-04] CSS变量，对应参考设计稿中的颜色系统
const CSS_VARS: React.CSSProperties = {
  '--bg': '#F2F4F7',
  '--card': '#FFFFFF',
  '--ink': '#1F2933',
  '--ink2': '#5B6B7B',
  '--ink3': '#97A3B2',
  '--line': '#E4E9EF',
  '--blue': '#1565B8',
  '--blue-d': '#0E4B8C',
  '--blue-soft': '#EAF2FB',
  '--ok': '#2F9E64',
  '--ok-soft': '#E5F4EC',
  '--radius': '14px',
} as React.CSSProperties;

// [修复 2026-09-04] 全局样式，对应参考设计稿中的CSS
const globalStyles = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif; background: var(--bg); color: var(--ink); line-height: 1.55; -webkit-font-smoothing: antialiased; }
  a { color: inherit; text-decoration: none; }
  
  /* ===== 容器 ===== */
  .wrap { max-width: 1160px; margin: 0 auto; padding: 22px 20px 56px; }
  
  /* ===== 顶栏 ===== */
  .topbar { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin-bottom: 22px; }
  .back { display: inline-flex; align-items: center; gap: 7px; font-size: 13.5px; color: var(--ink2); padding: 8px 13px; border: 1px solid var(--line); background: #fff; border-radius: 10px; transition: all 0.15s; cursor: pointer; }
  .back:hover { color: var(--blue); border-color: var(--blue); }
  .title-block { flex: 1 1 220px; min-width: 0; }
  .title-block h1 { font-size: 22px; font-weight: 700; letter-spacing: 0.3px; }
  .title-sub { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-top: 7px; font-size: 13px; color: var(--ink2); }
  .tag { display: inline-flex; align-items: center; padding: 2px 10px; background: #fff; border: 1px solid var(--line); border-radius: 20px; font-size: 12.5px; font-weight: 500; color: var(--ink); }
  .status-ok { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; background: var(--ok-soft); color: #1F7A4B; border-radius: 20px; font-size: 12.5px; font-weight: 600; }
  .status-ok i { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); display: inline-block; }
  .status-damaged { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; background: #FEF9C3; color: #A16207; border-radius: 20px; font-size: 12.5px; font-weight: 600; }
  .status-damaged i { width: 7px; height: 7px; border-radius: 50%; background: #EAB308; display: inline-block; }
  .status-severe { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; background: #FEE2E2; color: #DC2626; border-radius: 20px; font-size: 12.5px; font-weight: 600; }
  .status-severe i { width: 7px; height: 7px; border-radius: 50%; background: #DC2626; display: inline-block; }
  /* [新增 2026-09-09] 维修处理中状态徽章（此前缺失导致顶栏显示英文原值 repair_in_progress） */
  .status-repair { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; background: #E6F4FF; color: #1677FF; border-radius: 20px; font-size: 12.5px; font-weight: 600; }
  .status-repair i { width: 7px; height: 7px; border-radius: 50%; background: #1677FF; display: inline-block; }
  .status-removed { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; background: #F3F4F6; color: #6B7280; border-radius: 20px; font-size: 12.5px; font-weight: 600; }
  .status-removed i { width: 7px; height: 7px; border-radius: 50%; background: #6B7280; display: inline-block; }
  .top-actions { display: flex; align-items: center; gap: 10px; margin-left: auto; }
  .btn-edit { display: inline-flex; align-items: center; gap: 7px; padding: 9px 18px; background: var(--blue); color: #fff; border: none; border-radius: 10px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .btn-edit:hover { background: var(--blue-d); }
  
  /* ===== Hero：现场安装图 ===== */
  .hero { display: grid; grid-template-columns: minmax(0, 0.92fr) minmax(320px, 1fr); gap: 20px; margin-bottom: 20px; }
  .photo-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .photo-frame { position: relative; border-radius: var(--radius); overflow: hidden; background: #0E2436; box-shadow: 0 1px 2px rgba(14, 36, 54, 0.08), 0 10px 30px rgba(14, 36, 54, 0.12); }
  .photo-frame img { display: block; width: 100%; max-height: 500px; object-fit: cover; cursor: zoom-in; }
  .photo-badge { position: absolute; left: 14px; top: 14px; display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px; background: rgba(255, 255, 255, 0.95); color: var(--blue-d); border-radius: 8px; font-size: 12.5px; font-weight: 700; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.14); }
  .photo-badge::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px rgba(47, 158, 100, 0.28); }
  .zoom-btn { position: absolute; right: 14px; bottom: 14px; display: inline-flex; align-items: center; gap: 6px; padding: 8px 13px; background: rgba(15, 20, 25, 0.58); color: #fff; border: none; border-radius: 9px; font-size: 12.5px; font-weight: 500; cursor: pointer; transition: background 0.15s; }
  .zoom-btn:hover { background: rgba(15, 20, 25, 0.8); }
  .photo-caption { display: flex; align-items: flex-start; gap: 12px; padding: 14px 16px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); }
  .photo-caption .pin { flex: none; width: 36px; height: 36px; border-radius: 10px; background: var(--blue-soft); display: flex; align-items: center; justify-content: center; color: var(--blue); }
  /* [修复 2026-09-07] 重构为标题 + 两行列标签，保证地理位置、标识信息、安装时间、有效期、巡检时间对齐美观 */
  .caption-body { flex: 1; min-width: 0; }
  .caption-title { font-size: 14.5px; font-weight: 600; color: var(--ink); margin-bottom: 10px; }
  .caption-rows { display: flex; flex-direction: column; gap: 8px; }
  .caption-row { display: flex; flex-wrap: wrap; gap: 10px 24px; }
  .caption-item { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
  .caption-label { color: var(--ink2); font-size: 12px; white-space: nowrap; }
  .caption-value { color: var(--ink); font-size: 12.5px; font-weight: 500; white-space: nowrap; }
  /* [修复 2026-09-04] 大图下方分栏：位置说明 + 标识二维码 */
  .panel-split { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: stretch; }
  .qr-card { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 12px 14px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); min-width: 152px; }
  .qr-card .qr-title { font-size: 12.5px; font-weight: 700; color: var(--ink2); align-self: flex-start; display: flex; align-items: center; gap: 5px; }
  .qr-card .qr-canvas { border-radius: 6px; }
  .qr-download { display: inline-flex; align-items: center; justify-content: center; gap: 5px; width: 100%; padding: 7px 10px; margin-top: 2px; background: var(--blue); color: #fff; border: none; border-radius: 8px; font-size: 12.5px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .qr-download:hover { background: var(--blue-d); }
  .qr-card .qr-code-text { font-size: 11px; color: var(--ink3); text-align: center; word-break: break-all; line-height: 1.4; }
  
  /* ===== 信息面板 ===== */
  .info-panel { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px; }
  .card-head { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin-bottom: 13px; }
  .card-head::before { content: ""; width: 4px; height: 14px; border-radius: 2px; background: var(--blue); }
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 10px 14px; font-size: 13.5px; }
  .kv > div { display: contents; }
  .kv dt { color: var(--ink2); white-space: nowrap; }
  .kv dd { color: var(--ink); font-weight: 500; text-align: right; word-break: break-all; }
  .kv dd.muted { color: var(--ink3); font-weight: 400; }
  
  /* ===== 双栏信息 ===== */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  .kv .addr { font-weight: 400; color: var(--ink); }
  
  /* ===== 附件 ===== */
  .attach-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .attach-item { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 11px; background: #FAFBFC; min-width: 0; }
  .file-badge { flex: none; width: 44px; height: 44px; border-radius: 10px; background: var(--blue-soft); color: var(--blue); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 800; letter-spacing: 0.5px; }
  .thumb { flex: none; width: 44px; height: 44px; border-radius: 10px; object-fit: cover; background: #E7ECF2; cursor: zoom-in; }
  .attach-info { flex: 1 1 0; min-width: 0; }
  .attach-info strong { display: block; font-size: 13.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .attach-info span { display: block; font-size: 12px; color: var(--ink2); margin-top: 2px; }
  .attach-action { flex: none; display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--blue); font-weight: 600; cursor: pointer; padding: 6px 10px; border-radius: 8px; transition: background 0.15s; border: none; background: none; }
  .attach-action:hover { background: var(--blue-soft); }
  
  /* ===== 页脚 ===== */
  .foot { margin-top: 24px; text-align: center; font-size: 12px; color: var(--ink3); }
  
  /* ===== 灯箱 ===== */
  /* [修复 2026-09-08] z-index 提升至 3000：灯箱可能从 antd Modal（z-index 1000）内触发
     （如巡检记录详情、历史版本快照），原 1000 会被弹窗压在底层导致照片被遮挡 */
  .lightbox { position: fixed; inset: 0; z-index: 3000; display: none; align-items: center; justify-content: center; padding: 24px; }
  .lightbox.open { display: flex; }
  .lightbox-bg { position: absolute; inset: 0; background: rgba(10, 16, 22, 0.82); }
  .lightbox-body { position: relative; max-width: min(92vw, 1000px); max-height: 88vh; text-align: center; }
  .lightbox-body img { max-width: 100%; max-height: 80vh; border-radius: 10px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5); display: block; margin: 0 auto; }
  .lightbox-cap { color: #D7DFE7; font-size: 13px; margin-top: 12px; }
  .lightbox-close { position: absolute; right: -12px; top: -12px; width: 40px; height: 40px; border-radius: 50%; background: #fff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3); }
  .lightbox-close svg { width: 18px; height: 18px; stroke: #1F2933; }
  
  /* [修复 2026-09-04] 历史版本弹窗样式 */
  .ant-modal-content { border-radius: 14px; }
  .ant-modal-header { border-bottom: 1px solid var(--line); padding: 16px 24px; }
  .ant-modal-title { font-size: 18px; font-weight: 700; }
  .ant-list-item { transition: all 0.15s; }
  .ant-list-item:hover { background: #F8FAFC; border-color: var(--blue) !important; }
  .ant-descriptions-bordered .ant-descriptions-item-label { 
    background: #F8FAFC; 
    font-weight: 500; 
    color: var(--ink2); 
    width: 120px;
  }
  .ant-descriptions-bordered .ant-descriptions-item-content { color: var(--ink); }
  .ant-tag { border-radius: 4px; }
  
  /* ===== 响应式 ===== */
  @media (max-width: 900px) {
    .hero { grid-template-columns: 1fr; }
    .grid-2 { grid-template-columns: 1fr; }
    .attach-grid { grid-template-columns: 1fr; }
    .panel-split { grid-template-columns: 1fr; }
    .qr-card { min-width: 0; }
  }
  @media (max-width: 480px) {
    .wrap { padding: 16px 14px 40px; }
    .title-block h1 { font-size: 19px; }
    .photo-frame img { max-height: 360px; }
    .topbar { gap: 10px; }
  }
`;

// [修复 2026-09-04] 状态映射，对应参考设计稿中的标签颜色
const STATUS_MAP: Record<string, { label: string; className: string; color: string }> = {
  normal: { label: '正常', className: 'status-ok', color: '#1F7A4B' },
  damaged: { label: '轻微破损', className: 'status-damaged', color: '#A16207' },
  severely_damaged: { label: '严重损坏', className: 'status-severe', color: '#DC2626' },
  // [修复 2026-09-09] 补充维修处理中：此前缺失导致详情页顶栏显示英文原值
  repair_in_progress: { label: '维修处理中', className: 'status-repair', color: '#1677FF' },
  removed: { label: '已拆除', className: 'status-removed', color: '#6B7280' },
};

// [新增 2026-09-09] 顶栏白底描边按钮统一样式（维修记录/巡检历史/查看历史版本/版本更新共用）
const ghostBtnStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '7px',
  padding: '9px 18px',
  background: '#fff',
  color: 'var(--ink)',
  border: '1px solid var(--line)',
  borderRadius: '10px',
  fontSize: '14px',
  fontWeight: 600,
  cursor: 'pointer',
  transition: 'all 0.15s',
};

// [修复 2026-09-04] 空值展示组件
const DisplayValue: React.FC<{ value?: string | null; muted?: boolean }> = ({ value, muted }) => {
  if (!value) return <span className="muted">未填写</span>;
  return <span className={muted ? 'muted' : ''}>{value}</span>;
};

// [修复 2026-09-04] 灯箱组件
const Lightbox: React.FC<{
  isOpen: boolean;
  imageUrl: string;
  caption: string;
  onClose: () => void;
}> = ({ isOpen, imageUrl, caption, onClose }) => {
  return (
    <div className={`lightbox ${isOpen ? 'open' : ''}`} role="dialog" aria-modal="true" aria-label="查看大图">
      <div className="lightbox-bg" onClick={onClose} />
      <div className="lightbox-body">
        <button className="lightbox-close" onClick={onClose} type="button" aria-label="关闭">
          <svg viewBox="0 0 24 24" fill="none" strokeWidth="2.4" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" />
          </svg>
        </button>
        <img src={imageUrl} alt={caption} onClick={onClose} />
        <div className="lightbox-cap">{caption}</div>
      </div>
    </div>
  );
};

const SignageDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<Signage | null>(null);
  const [photos, setPhotos] = useState<SignagePhoto[]>([]);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxImage, setLightboxImage] = useState('');
  const [lightboxCaption, setLightboxCaption] = useState('');
  // [修复 2026-09-04] 新增律师版本快照查看相关状态
  const [historyModalVisible, setHistoryModalVisible] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyList, setHistoryList] = useState<SignageHistory[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState<SignageHistory | null>(null);
  const [snapshotDetailVisible, setSnapshotDetailVisible] = useState(false);
  // [新增 2026-09-07] 巡检历史弹窗状态
  const [inspectionModalVisible, setInspectionModalVisible] = useState(false);
  const [inspectionList, setInspectionList] = useState<SignageInspectionRecord[]>([]);
  const [inspectionTotal, setInspectionTotal] = useState(0);
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [inspectionDetail, setInspectionDetail] = useState<SignageInspectionRecord | null>(null);
  // [新增 2026-09-09] 维修记录弹窗状态：展示该标识全部维修记录（维修前/后照片对比）
  const [repairModalVisible, setRepairModalVisible] = useState(false);
  const [repairList, setRepairList] = useState<SignageRepairRecord[]>([]);
  const [repairLoading, setRepairLoading] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      getSignage(Number(id)),
      getSignagePhotos(Number(id)),
    ])
      .then(([signage, pics]) => {
        setData(signage);
        setPhotos(pics);
      })
      .catch(() => message.error('获取标识信息失败'))
      .finally(() => setLoading(false));
  }, [id]);

  // [修复 2026-09-04] 获取历史版本列表
  const fetchHistory = async () => {
    if (!id) return;
    setHistoryLoading(true);
    try {
      const result = await getSignageHistory(Number(id), { page: 1, page_size: 50 });
      setHistoryList(result.items);
    } catch {
      message.error('获取历史版本失败');
    } finally {
      setHistoryLoading(false);
    }
  };

  // [修复 2026-09-04] 打开历史版本弹窗
  const openHistoryModal = () => {
    setHistoryModalVisible(true);
    fetchHistory();
  };

  // [新增 2026-09-07] 获取该标识的巡检历史记录
  const fetchInspections = async () => {
    if (!data?.code) return;
    setInspectionLoading(true);
    try {
      const r = await getSignageInspections({ code: data.code, page: 1, page_size: 100 });
      setInspectionList(r.items);
      setInspectionTotal(r.total);
    } catch {
      message.error('获取巡检历史失败');
    } finally {
      setInspectionLoading(false);
    }
  };

  // [新增 2026-09-07] 打开巡检历史弹窗
  const openInspectionModal = () => {
    setInspectionModalVisible(true);
    fetchInspections();
  };

  // [新增 2026-09-09] 获取该标识的全部维修记录（含维修前/后照片对比）
  const fetchRepairs = async () => {
    if (!id) return;
    setRepairLoading(true);
    try {
      const list = await getSignageRepairs(Number(id));
      setRepairList(list);
    } catch {
      message.error('获取维修记录失败');
    } finally {
      setRepairLoading(false);
    }
  };

  // [新增 2026-09-09] 打开维修记录弹窗
  const openRepairModal = () => {
    setRepairModalVisible(true);
    fetchRepairs();
  };

  /** [新增 2026-09-14] 一键复制标识编码（与标识管理列表的编码列行为一致） */
  const handleCopyCode = async () => {
    const code = data?.code;
    if (!code) return;
    const ok = await copyText(code);
    if (ok) message.success(`已复制编码：${code}`);
    else message.error('复制失败，请手动选中复制');
  };

  // [修复 2026-09-04] 查看快照详情
  const viewSnapshotDetail = (snapshot: SignageHistory) => {
    setSelectedSnapshot(snapshot);
    setSnapshotDetailVisible(true);
  };

  // [修复 2026-09-04] 打开灯箱
  const openLightbox = (imageUrl: string, caption: string) => {
    setLightboxImage(imageUrl);
    setLightboxCaption(caption);
    setLightboxOpen(true);
  };

  // [修复 2026-09-04] 关闭灯箱
  const closeLightbox = () => {
    setLightboxOpen(false);
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!data) return <Empty description="标识不存在" />;

  const statusInfo = STATUS_MAP[data.status] || { label: data.status, className: 'status-removed', color: '#6B7280' };

  // [修复 2026-09-04] 获取现场照片 URL（优先使用 installation_photo，否则取 photos 列表中第一张）
  const mainPhotoUrl = data.installation_photo
    ? getOriginalUrl(data.installation_photo)
    : photos.length > 0 && photos[0].photo_url
      ? getOriginalUrl(photos[0].photo_url)
      : null;

  // [修复 2026-09-08] 二维码只编码「纯标识编号」，扫码得到的就是编号本身，
  // 可直接与后端 by-code 精确匹配（去掉“标识编码：/院区：/位置：”等前缀，避免扫码后无法匹配）。
  // 院区/位置等信息仍显示在二维码下方的文字区域，不写入码内。
  const qrContent = data.code || `标识ID：${data.id}`;

  // [修复 2026-09-04] 下载二维码（合成二维码 + 编号 + 位置文字为单张图片）
  const handleDownloadQr = () => {
    const qrCanvas = document.getElementById('signage-qr-canvas') as HTMLCanvasElement | null;
    if (!qrCanvas) {
      message.error('二维码尚未生成');
      return;
    }
    const sd = data;
    const codeText = `编号：${sd.code || '—'}`;
    const locText = `位置：${sd.location_desc || '未填写安装位置'}`;
    const padding = 24;
    const titleH = 36;
    const textLineH = 22;
    const lineGap = 10;
    // 按字符数估算换行（最多每行约 18 个汉字）
    const wrap = (text: string, maxChars: number): string[] => {
      const lines: string[] = [];
      let line = '';
      for (const ch of text) {
        line += ch;
        if (line.length >= maxChars) {
          lines.push(line);
          line = '';
        }
      }
      if (line) lines.push(line);
      return lines;
    };
    const locLines = wrap(locText, 18);
    const textHeight = textLineH * (1 + locLines.length) + lineGap;
    const totalW = qrCanvas.width + padding * 2;
    const totalH = padding + titleH + qrCanvas.height + textHeight + padding;

    const out = document.createElement('canvas');
    out.width = totalW;
    out.height = totalH;
    const ctx = out.getContext('2d');
    if (!ctx) {
      message.error('当前浏览器不支持生成图片');
      return;
    }
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, totalW, totalH);
    // 标题
    ctx.fillStyle = '#1F2933';
    ctx.font = 'bold 20px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('标识二维码', totalW / 2, padding + 20);
    // 二维码
    ctx.drawImage(qrCanvas, padding, padding + titleH);
    // 编号
    ctx.font = '15px sans-serif';
    let y = padding + titleH + qrCanvas.height + lineGap + textLineH;
    ctx.fillText(codeText, totalW / 2, y);
    // 位置（多行）
    ctx.fillStyle = '#5B6B7B';
    locLines.forEach((ln) => {
      y += textLineH;
      ctx.fillText(ln, totalW / 2, y);
    });
    const link = document.createElement('a');
    link.download = `标识二维码_${sd.code || sd.id}.png`;
    link.href = out.toDataURL('image/png');
    link.click();
  };

  // [修复 2026-09-04] 构建附件列表
  const attachments: { name: string; url: string; type: string; isImage: boolean }[] = [];
  if (data.design_photo) {
    const url = getOriginalUrl(data.design_photo) || data.design_photo;
    const fileName = data.design_photo.split('/').pop() || '设计文件';
    attachments.push({ name: fileName, url, type: '设计文件', isImage: false });
  }
  if (data.installation_photo) {
    const url = getOriginalUrl(data.installation_photo) || data.installation_photo;
    const fileName = data.installation_photo.split('/').pop() || '现场照片';
    attachments.push({ name: fileName, url, type: '现场照片', isImage: true });
  }
  photos.forEach((p) => {
    if (p.photo_url) {
      const url = getOriginalUrl(p.photo_url) || p.photo_url;
      const fileName = p.photo_url.split('/').pop() || '附件';
      const label = p.photo_type === 'installation' ? '现场照片'
        : p.photo_type === 'design' ? '设计文件'
        : p.caption || '附件';
      attachments.push({ name: fileName, url, type: label, isImage: true });
    }
  });

  return (
    <>
      {/* [修复 2026-09-04] 注入全局样式 */}
      <style dangerouslySetInnerHTML={{ __html: globalStyles }} />
      
      {/* [修复 2026-09-04] 应用CSS变量 */}
      <div style={CSS_VARS}>
        <div className="wrap">
          {/* ===== 顶栏 ===== */}
          <header className="topbar">
            <a className="back" onClick={() => navigate('/signages')} aria-label="返回列表">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              返回列表
            </a>
            <div className="title-block">
              <h1>标识详情</h1>
              <div className="title-sub">
                <span className="tag">{data.category}</span>
                <span className={statusInfo.className}>
                  <i style={{ background: statusInfo.color }}></i>
                  {statusInfo.label}
                </span>
                {data.code && (
                  // [调整 2026-09-14] 标识编码支持一键复制（与标识管理列表编码列一致）。
                  // 用 inline-flex 包裹以保证图标与文字在同一基线上，高度收窄至 22px 适配 13px 文字行
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                    标识编码 {data.code}
                    <Tooltip title="复制编码">
                      <Button
                        type="text"
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={handleCopyCode}
                        aria-label={`复制编码 ${data.code}`}
                        style={{ height: 22, padding: '0 4px' }}
                      />
                    </Tooltip>
                  </span>
                )}
              </div>
            </div>
            <div className="top-actions">
              {/* [新增 2026-09-09] 维修记录按钮：位于巡检历史旁，展示该标识全部维修记录（维修前/后照片对比）
                  [调整 2026-09-15] 遵循「无权限按钮直接隐藏」规则：无 signage.repair（维修记录）权限时不渲染该按钮 */}
              {hasPermission(user, PERM_SIGNAGE_REPAIR) && (
                <button className="btn-history" type="button" onClick={openRepairModal} style={ghostBtnStyle}>
                  <ToolOutlined />
                  维修记录
                </button>
              )}
              {/* [新增 2026-09-07] 巡检历史按钮（位于历史版本左侧）
                  [调整 2026-09-15] 无 signage.inspection（标识巡检）权限时不渲染该按钮 */}
              {hasPermission(user, PERM_SIGNAGE_INSPECTION) && (
                <button className="btn-history" type="button" onClick={openInspectionModal} style={ghostBtnStyle}>
                  <FileSearchOutlined />
                  巡检历史
                </button>
              )}
              {/* [修复 2026-09-04] 新增查看历史版本按钮
                  [调整 2026-09-15] 历史版本由「版本更新」入口写入，与编辑能力配套：无 signage.edit 权限时不渲染该按钮 */}
              {hasPermission(user, PERM_SIGNAGE_EDIT) && (
                <button className="btn-history" type="button" onClick={openHistoryModal} style={ghostBtnStyle}>
                  <HistoryOutlined />
                  查看历史版本
                </button>
              )}
              {/* [新增 2026-09-09] 版本更新按钮（位于编辑左侧）：仅此入口的修改会写入历史版本；样式与编辑按钮一致（蓝底主按钮） */}
              {hasPermission(user, PERM_SIGNAGE_EDIT) && (
                <button
                  className="btn-edit"
                  type="button"
                  onClick={() => navigate(`/signages/version-update/${id}`)}
                >
                  <SyncOutlined />
                  版本更新
                </button>
              )}
              {hasPermission(user, PERM_SIGNAGE_EDIT) && (
                <button className="btn-edit" type="button" onClick={() => navigate(`/signages/edit/${id}`)}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                  </svg>
                  编辑
                </button>
              )}
            </div>
          </header>

          {/* ===== Hero：现场安装图 + 标识信息 ===== */}
          <section className="hero">
            <div className="photo-panel">
              <figure className="photo-frame">
                {mainPhotoUrl ? (
                  <>
                    <img
                      src={mainPhotoUrl}
                      alt={`${data.name || '标识'}现场安装图`}
                      onClick={() => openLightbox(mainPhotoUrl, `${data.name || '标识'}现场安装图`)}
                    />
                    <span className="photo-badge">现场安装</span>
                    <button
                      className="zoom-btn"
                      type="button"
                      onClick={() => openLightbox(mainPhotoUrl, `${data.name || '标识'}现场安装图`)}
                    >
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="11" cy="11" r="8" />
                        <path d="m21 21-4.35-4.35M11 8v6M8 11h6" />
                      </svg>
                      点击查看大图
                    </button>
                  </>
                ) : (
                  <div style={{ textAlign: 'center', color: '#666', padding: '60px 0' }}>
                    <FileOutlined style={{ fontSize: 48, display: 'block', marginBottom: 8, color: '#ccc' }} />
                    <span>暂无照片</span>
                  </div>
                )}
              </figure>
              {/* [修复 2026-09-04] 大图下方分栏：左侧位置说明 + 右侧标识二维码 */}
              <div className="panel-split">
                {/* [修复 2026-09-07] 补充显示：地理位置（院区/楼栋/楼层）、标识信息（尺寸规格）、安装时间、有效期、最近一次巡检时间，并统一对齐 */}
                <div className="photo-caption">
                  <span className="pin">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z" />
                      <circle cx="12" cy="10" r="3" />
                    </svg>
                  </span>
                  <div className="caption-body">
                    <div className="caption-title">{data.location_desc || '未填写安装位置'}</div>
                    <div className="caption-rows">
                      <div className="caption-row">
                        <div className="caption-item"><span className="caption-label">院区</span><span className="caption-value">{data.campus || '-'}</span></div>
                        <div className="caption-item"><span className="caption-label">楼栋</span><span className="caption-value">{data.building || '-'}</span></div>
                        <div className="caption-item"><span className="caption-label">楼层</span><span className="caption-value">{data.floor || '-'}</span></div>
                        {/* [新增 2026-09-12] 区域：多选，逗号分隔存储，直接展示即可 */}
                        <div className="caption-item"><span className="caption-label">区域</span><span className="caption-value">{data.area || '-'}</span></div>
                      </div>
                      <div className="caption-row">
                        <div className="caption-item"><span className="caption-label">尺寸规格</span><span className="caption-value">{data.size_spec || '-'}</span></div>
                        <div className="caption-item"><span className="caption-label">安装时间</span><span className="caption-value">{data.install_date || '-'}</span></div>
                        <div className="caption-item"><span className="caption-label">标识有效期</span><span className="caption-value">{data.validity_type === 'temporary' ? `至 ${data.validity_until || '未填写'}` : '长期有效'}</span></div>
                        <div className="caption-item"><span className="caption-label">最近一次巡检</span><span className="caption-value">{data.last_inspection_date || '-'}</span></div>
                      </div>
                    </div>
                  </div>
                </div>
                {/* [修复 2026-09-04] 标识二维码卡片：自动生成，可下载（含二维码+编号+位置） */}
                <div className="qr-card">
                  <div className="qr-title">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="3" width="7" height="7" rx="1" />
                      <rect x="14" y="3" width="7" height="7" rx="1" />
                      <rect x="3" y="14" width="7" height="7" rx="1" />
                      <path d="M14 14h3v3M21 14v7h-7v-3" />
                    </svg>
                    标识二维码
                  </div>
                  <QRCodeCanvas
                    id="signage-qr-canvas"
                    value={qrContent}
                    size={120}
                    level="M"
                    marginSize={1}
                    className="qr-canvas"
                  />
                  <div className="qr-code-text">编号：{data.code || '—'}</div>
                  <button className="qr-download" type="button" onClick={handleDownloadQr}>
                    <DownloadOutlined />
                    下载二维码
                  </button>
                </div>
              </div>
            </div>

            <aside className="info-panel">
              <div className="card">
                <div className="card-head">标识信息</div>
                <dl className="kv">
                  <div><dt>标识名称</dt><dd><DisplayValue value={data.name} /></dd></div>
                  <div><dt>分类</dt><dd><DisplayValue value={data.category} /></dd></div>
                  <div><dt>类别</dt><dd><DisplayValue value={data.category_type} /></dd></div>
                  <div><dt>材质</dt><dd><DisplayValue value={data.material} /></dd></div>
                  <div><dt>规格尺寸</dt><dd><DisplayValue value={data.size_spec} /></dd></div>
                  <div><dt>所属区域</dt><dd><DisplayValue value={data.zone_type} /></dd></div>
                  <div><dt>OA单号</dt><dd><DisplayValue value={data.oa_number} muted /></dd></div>
                </dl>
              </div>
              <div className="card">
                <div className="card-head">显示文本</div>
                <dl className="kv">
                  <div><dt>中文文本</dt><dd><DisplayValue value={data.display_text_cn} /></dd></div>
                  <div><dt>英文文本</dt><dd><DisplayValue value={data.display_text_en} /></dd></div>
                </dl>
              </div>
            </aside>
          </section>

          {/* ===== 位置信息 + 安装信息 ===== */}
          <section className="grid-2">
            <div className="card">
              <div className="card-head">位置信息</div>
              <dl className="kv">
                <div><dt>所属区域</dt><dd><DisplayValue value={data.zone_type} /></dd></div>
                <div><dt>院区</dt><dd><DisplayValue value={data.campus} /></dd></div>
                <div><dt>楼栋</dt><dd><DisplayValue value={data.building} muted /></dd></div>
                <div><dt>楼层</dt><dd><DisplayValue value={data.floor} muted /></dd></div>
                {/* [新增 2026-09-12] 具体区域（选填、可多选，逗号分隔展示）；与上方「所属区域」类型区分 */}
                <div><dt>区域</dt><dd><DisplayValue value={data.area} muted /></dd></div>
                <div><dt>安装位置描述</dt><dd className="addr"><DisplayValue value={data.location_desc} /></dd></div>
              </dl>
            </div>
            <div className="card">
              <div className="card-head">安装信息</div>
              <dl className="kv">
                <div><dt>安装日期</dt><dd><DisplayValue value={data.install_date} /></dd></div>
                <div><dt>质保到期日</dt><dd><DisplayValue value={data.warranty_expire} /></dd></div>
                <div><dt>制作厂商</dt><dd><DisplayValue value={data.manufacturer} /></dd></div>
                <div><dt>厂商联系方式</dt><dd><DisplayValue value={data.vendor_contact} /></dd></div>
              </dl>
            </div>
          </section>

          {/* ===== 附件资料 ===== */}
          {attachments.length > 0 && (
            <section className="card">
              <div className="card-head">附件资料</div>
              <div className="attach-grid">
                {attachments.map((att, idx) => (
                  <div className="attach-item" key={idx}>
                    {att.isImage ? (
                      <img
                        className="thumb"
                        src={att.url}
                        alt={att.name}
                        onClick={() => openLightbox(att.url, att.name)}
                      />
                    ) : (
                      <span className="file-badge">
                        {(att.name.split('.').pop() || 'FILE').toUpperCase().slice(0, 4)}
                      </span>
                    )}
                    <div className="attach-info">
                      <strong>{att.name}</strong>
                      <span>{att.type}</span>
                    </div>
                    <button
                      className="attach-action"
                      onClick={() => att.isImage ? openLightbox(att.url, att.name) : window.open(att.url, '_blank')}
                    >
                      {att.isImage ? (
                        <>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
                            <circle cx="12" cy="12" r="3" />
                          </svg>
                          查看
                        </>
                      ) : (
                        <>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <path d="m7 10 5 5 5-5M12 15V3" />
                          </svg>
                          下载
                        </>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          <footer className="foot">数据由医院标识标牌管理系统提供</footer>
        </div>
      </div>

      {/* [修复 2026-09-04] 灯箱组件 */}
      <Lightbox
        isOpen={lightboxOpen}
        imageUrl={lightboxImage}
        caption={lightboxCaption}
        onClose={closeLightbox}
      />

      {/* [修复 2026-09-04] 历史版本弹窗（[修复 2026-09-09] 修正标题错别字：律师→历史） */}
      <Modal
        title="历史版本快照查看"
        open={historyModalVisible}
        onCancel={() => setHistoryModalVisible(false)}
        footer={null}
        width={800}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <div style={{ marginBottom: 16, color: 'var(--ink2)', fontSize: 13 }}>
          查看标识的历史变更版本，每个版本包含当时的完整信息快照
        </div>
        <List
          loading={historyLoading}
          dataSource={historyList}
          locale={{ emptyText: '暂无历史记录' }}
          renderItem={(item) => (
            <List.Item
              style={{ 
                padding: '12px 16px', 
                border: '1px solid var(--line)', 
                borderRadius: 8, 
                marginBottom: 8,
                cursor: 'pointer',
                transition: 'all 0.15s'
              }}
              onClick={() => viewSnapshotDetail(item)}
              actions={[
                <Button 
                  key="view" 
                  type="link" 
                  icon={<EyeOutlined />}
                  style={{ color: 'var(--blue)' }}
                >
                  查看详情
                </Button>
              ]}
            >
              <List.Item.Meta
                avatar={
                  <div style={{
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    background: item.snapshot ? 'var(--blue-soft)' : '#F3F4F6',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: item.snapshot ? 'var(--blue)' : '#9CA3AF'
                  }}>
                    <ClockCircleOutlined />
                  </div>
                }
                title={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600 }}>
                      {/* [修复 2026-09-09] 字段名转中文（如 installation_photo → 现场照片） */}
                      {item.field_name ? `变更: ${signageFieldLabel(item.field_name)}` : '创建标识'}
                    </span>
                    {item.oa_number && (
                      <Tag color="blue" style={{ margin: 0 }}>
                        OA: {item.oa_number}
                      </Tag>
                    )}
                  </div>
                }
                description={
                  <div style={{ fontSize: 12, color: 'var(--ink2)' }}>
                    {/* [修复 2026-09-08] 后端时间为 UTC，按本地时区转换显示（原样显示差 8 小时） */}
                    <div>变更时间: {formatDateTimeStandard(item.changed_at)}</div>
                    <div>操作人: {item.changed_by || '未知'}</div>
                    {item.old_value && (
                      <div style={{ marginTop: 4 }}>
                        {/* [修复 2026-09-09] 枚举值转中文（如 repair_in_progress → 维修处理中） */}
                        <span style={{ color: '#DC2626' }}>旧值: {formatSignageFieldValue(item.field_name, item.old_value)}</span>
                        {' → '}
                        <span style={{ color: '#16A34A' }}>新值: {formatSignageFieldValue(item.field_name, item.new_value)}</span>
                      </div>
                    )}
                  </div>
                }
              />
            </List.Item>
          )}
        />
      </Modal>

      {/* [修复 2026-09-04] 快照详情弹窗 */}
      <Modal
        title="版本快照详情"
        open={snapshotDetailVisible}
        onCancel={() => setSnapshotDetailVisible(false)}
        footer={[
          <Button key="close" onClick={() => setSnapshotDetailVisible(false)}>
            关闭
          </Button>
        ]}
        width={900}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        {selectedSnapshot && (
          <div>
            <div style={{ marginBottom: 16, padding: 12, background: '#F8FAFC', borderRadius: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div>
                  <strong>变更信息</strong>
                  <div style={{ fontSize: 12, color: 'var(--ink2)', marginTop: 4 }}>
                    时间: {formatDateTimeStandard(selectedSnapshot.changed_at)}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 12, color: 'var(--ink2)' }}>操作人</div>
                  <div style={{ fontWeight: 500 }}>{selectedSnapshot.changed_by || '未知'}</div>
                </div>
              </div>
              {selectedSnapshot.field_name && (
                <div style={{ fontSize: 13 }}>
                  <span style={{ color: 'var(--ink2)' }}>变更字段: </span>
                  {/* [修复 2026-09-09] 字段名与枚举值转中文 */}
                  <Tag>{signageFieldLabel(selectedSnapshot.field_name)}</Tag>
                  {selectedSnapshot.old_value && (
                    <>
                      <span style={{ color: '#DC2626', marginLeft: 8 }}>旧值: {formatSignageFieldValue(selectedSnapshot.field_name, selectedSnapshot.old_value)}</span>
                      <span style={{ margin: '0 4px' }}>→</span>
                      <span style={{ color: '#16A34A' }}>新值: {formatSignageFieldValue(selectedSnapshot.field_name, selectedSnapshot.new_value)}</span>
                    </>
                  )}
                </div>
              )}
            </div>

            {selectedSnapshot.snapshot ? (
              <div>
                <Divider orientation="left" orientationMargin={0}>标识快照</Divider>
                <Descriptions bordered column={2} size="small">
                  <Descriptions.Item label="标识编码">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').code || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="标识名称">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').name || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="分类">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').category || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    {/* [修复 2026-09-09] 补充 repair_in_progress 分支：此前快照状态为维修处理中时会错误显示为「已拆除」 */}
                    <Tag color={
                      JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'normal' ? 'green' :
                      JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'damaged' ? 'orange' :
                      JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'severely_damaged' ? 'red' :
                      JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'repair_in_progress' ? 'processing' : 'default'
                    }>
                      {JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'normal' ? '正常' :
                       JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'damaged' ? '轻微破损' :
                       JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'severely_damaged' ? '严重损坏' :
                       JSON.parse(selectedSnapshot.snapshot ?? '{}').status === 'repair_in_progress' ? '维修处理中' : '已拆除'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="材质">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').material || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="规格尺寸">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').size_spec || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="院区">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').campus || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="楼栋">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').building || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="楼层">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').floor || '未填写'}
                  </Descriptions.Item>
                  {/* [新增 2026-09-12] 历史快照中的区域（旧快照无该字段时显示「未填写」） */}
                  <Descriptions.Item label="区域">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').area || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="安装位置">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').location_desc || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="安装日期">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').install_date || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="质保到期日">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').warranty_expire || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="中文文本" span={2}>
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').display_text_cn || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="英文文本" span={2}>
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').display_text_en || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="OA单号">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').oa_number || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="制作厂商">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').manufacturer || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="厂商联系方式">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').vendor_contact || '未填写'}
                  </Descriptions.Item>
                  <Descriptions.Item label="设计文件">
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').design_photo ? (
                      <a 
                        href={getOriginalUrl(JSON.parse(selectedSnapshot.snapshot ?? '{}').design_photo) ?? ''} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        style={{ color: 'var(--blue)' }}
                      >
                        查看文件
                      </a>
                    ) : '未上传'}
                  </Descriptions.Item>
                  <Descriptions.Item label="现场照片" span={2}>
                    {JSON.parse(selectedSnapshot.snapshot ?? '{}').installation_photo ? (
                      <img 
                        src={getOriginalUrl(JSON.parse(selectedSnapshot.snapshot ?? '{}').installation_photo) ?? ''} 
                        alt="现场照片" 
                        style={{ maxWidth: 200, maxHeight: 150, borderRadius: 8, cursor: 'pointer' }}
                        onClick={() => {
                          setLightboxImage(getOriginalUrl(JSON.parse(selectedSnapshot.snapshot ?? '{}').installation_photo) ?? '');
                          setLightboxCaption('历史版本现场照片');
                          setLightboxOpen(true);
                        }}
                      />
                    ) : '未上传'}
                  </Descriptions.Item>
                </Descriptions>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--ink3)' }}>
                <div style={{ fontSize: 48, marginBottom: 16 }}>📷</div>
                <div>此版本无快照数据</div>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* [新增 2026-09-07] 巡检历史弹窗 */}
      <Modal
        title="巡检历史"
        open={inspectionModalVisible}
        onCancel={() => setInspectionModalVisible(false)}
        footer={null}
        width={760}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        {data?.code ? (
          <>
            <div style={{ marginBottom: 16, color: 'var(--ink2)', fontSize: 13 }}>
              标识编码：{data.code} · 共 {inspectionTotal} 条巡检记录
            </div>
            <List
              loading={inspectionLoading}
              dataSource={inspectionList}
              locale={{ emptyText: '暂无巡检记录' }}
              renderItem={(item) => {
                const m = STATUS_MAP[item.result] || { label: item.result, color: '#6B7280' };
                return (
                  <List.Item
                    style={{
                      padding: '12px 16px',
                      border: '1px solid var(--line)',
                      borderRadius: 8,
                      marginBottom: 8,
                      cursor: 'pointer',
                      transition: 'all 0.15s'
                    }}
                    onClick={() => setInspectionDetail(item)}
                    actions={[
                      <Button
                        key="view"
                        type="link"
                        icon={<EyeOutlined />}
                        style={{ color: 'var(--blue)' }}
                      >
                        查看详情
                      </Button>
                    ]}
                  >
                    <List.Item.Meta
                      avatar={
                        <div style={{
                          width: 40,
                          height: 40,
                          borderRadius: '50%',
                          background: 'var(--blue-soft)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}>
                          <span style={{
                            width: 12,
                            height: 12,
                            borderRadius: '50%',
                            background: m.color,
                            display: 'inline-block'
                          }} />
                        </div>
                      }
                      title={
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontWeight: 600 }}>巡检结果：{m.label}</span>
                        </div>
                      }
                      description={
                        <div style={{ fontSize: 12, color: 'var(--ink2)' }}>
                          {/* [修复 2026-09-08] UTC 时间按本地时区转换显示 */}
                          <div>巡检时间：{formatDateTimeStandard(item.created_at)}</div>
                          <div>
                            提交人：{item.inspector || '未知'}
                            {item.notes ? ` · 备注：${item.notes}` : ''}
                          </div>
                        </div>
                      }
                    />
                  </List.Item>
                );
              }}
            />
          </>
        ) : (
          <Empty description="该标识暂无编码，无法查询巡检记录" />
        )}
      </Modal>

      {/* [新增 2026-09-09] 维修记录弹窗：展示该标识全部维修记录，每条含维修前/后照片对比；缺图显示"暂无现场照片" */}
      <Modal
        title="维修记录"
        open={repairModalVisible}
        onCancel={() => setRepairModalVisible(false)}
        footer={null}
        width={860}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        <div style={{ marginBottom: 16, color: 'var(--ink2)', fontSize: 13 }}>
          共 {repairList.length} 条维修记录 · 维修前照片取自巡检时上传的现场照片
        </div>
        {repairList.length === 0 && !repairLoading ? (
          <Empty description="暂无维修记录" />
        ) : (
          <List
            loading={repairLoading}
            dataSource={repairList}
            locale={{ emptyText: '暂无维修记录' }}
            renderItem={(item) => {
              const done = !!item.completed_at;
              const partyLabel = item.repair_party === 'vendor'
                ? `供应商维修${item.supplier_name ? `（${item.supplier_name}）` : ''}`
                : '工程部维修';
              const beforeUrl = item.repair_photo_before ? (getOriginalUrl(item.repair_photo_before) || '') : '';
              const afterUrl = item.repair_photo ? (getOriginalUrl(item.repair_photo) || '') : '';
              const placeholderStyle: React.CSSProperties = {
                height: 140,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#F8FAFC',
                border: '1px dashed var(--line)',
                borderRadius: 8,
                color: 'var(--ink3)',
                fontSize: 12,
              };
              return (
                <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 12, background: '#fff' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                    <Tag color={done ? 'green' : 'processing'} style={{ margin: 0 }}>
                      {done ? '已完成维修' : '维修处理中'}
                    </Tag>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{partyLabel}</span>
                    {item.oa_number && <Tag style={{ margin: 0 }}>OA: {item.oa_number}</Tag>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--ink2)', marginBottom: 10 }}>
                    发起：{item.started_at ? formatDateTimeStandard(item.started_at) : '—'}（{item.started_by || '未知'}）
                    {done && (
                      <>
                        {' · '}完成：{item.completed_at ? formatDateTimeStandard(item.completed_at) : '—'}（{item.completed_by || '未知'}）
                      </>
                    )}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink2)', marginBottom: 6 }}>维修前照片</div>
                      {beforeUrl ? (
                        <img
                          src={beforeUrl}
                          alt="维修前照片"
                          style={{ width: '100%', maxHeight: 220, objectFit: 'cover', borderRadius: 8, cursor: 'zoom-in', background: '#E7ECF2' }}
                          onClick={() => openLightbox(beforeUrl, '维修前照片')}
                        />
                      ) : (
                        <div style={placeholderStyle}>暂无现场照片</div>
                      )}
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink2)', marginBottom: 6 }}>维修后照片</div>
                      {afterUrl ? (
                        <img
                          src={afterUrl}
                          alt="维修后照片"
                          style={{ width: '100%', maxHeight: 220, objectFit: 'cover', borderRadius: 8, cursor: 'zoom-in', background: '#E7ECF2' }}
                          onClick={() => openLightbox(afterUrl, '维修后照片')}
                        />
                      ) : (
                        <div style={placeholderStyle}>暂无现场照片</div>
                      )}
                    </div>
                  </div>
                </div>
              );
            }}
          />
        )}
      </Modal>

      {/* [新增 2026-09-07] 单次巡检记录详情弹窗 */}
      <Modal
        title="巡检记录详情"
        open={!!inspectionDetail}
        onCancel={() => setInspectionDetail(null)}
        footer={[
          <Button key="close" onClick={() => setInspectionDetail(null)}>
            关闭
          </Button>
        ]}
        width={520}
      >
        {inspectionDetail && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="巡检时间">
              {/* [修复 2026-09-08] UTC 时间按本地时区转换显示 */}
              {formatDateTimeStandard(inspectionDetail.created_at)}
            </Descriptions.Item>
            <Descriptions.Item label="标识编码">
              {inspectionDetail.signage_code || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="标识名称">
              {inspectionDetail.signage_name || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="巡检结果">
              <Tag color={(STATUS_MAP[inspectionDetail.result] || {}).color || 'default'}>
                {(STATUS_MAP[inspectionDetail.result] || {}).label || inspectionDetail.result}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="提交人">
              {inspectionDetail.inspector || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="备注">
              {inspectionDetail.notes || '-'}
            </Descriptions.Item>
            {/* [新增 2026-09-07] 展示巡检提交时上传的现场照片（若有） */}
            {inspectionDetail.photo && (
              <Descriptions.Item label="现场照片">
                <img
                  src={getOriginalUrl(inspectionDetail.photo) || ''}
                  alt="巡检现场照片"
                  style={{ maxWidth: '100%', maxHeight: 240, objectFit: 'contain', borderRadius: 6, cursor: 'zoom-in' }}
                  onClick={() => openLightbox(getOriginalUrl(inspectionDetail.photo ?? null) || '', '巡检现场照片')}
                />
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </>
  );
};

export default SignageDetail;
