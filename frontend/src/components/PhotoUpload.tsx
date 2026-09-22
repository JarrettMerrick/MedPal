import React, { useRef, useState, useMemo, useEffect, useCallback } from 'react';
import { downloadBlob } from '../utils/fileUtils';
import { Modal, Button, Progress, Alert, Typography, Image, Space, Tag, theme } from 'antd';
import { InboxOutlined, DownloadOutlined, EyeOutlined, SwapOutlined, DeleteOutlined } from '@ant-design/icons';
import { uploadApi } from '../api/client';
import { getThumbnailUrl, getOriginalUrl, getOriginalPreferredCandidates } from '../utils/imageUtils';
import SafeImage from './SafeImage';
import { setFileToken } from '../utils/tokenStore';
import PhotoCropper from './PhotoCropper';

const { Text } = Typography;
const { useToken } = theme;

// ==================== 常量 ====================

/** 分片大小 2MB */
const CHUNK_SIZE = 2 * 1024 * 1024;
/** 最大重试次数 */
const MAX_RETRIES = 3;
/** localStorage 键前缀 */
const LS_KEY_PREFIX = 'chunk_upload_';
/** 断点续传记录过期时间（7天） */
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
/** 最多保留记录数 */
const MAX_RECORDS = 100;

// ==================== 工具函数 ====================

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getErrMsg(e: { code?: string; message?: string; response?: { status?: number; data?: { detail?: unknown } } }): string {
  const msg = e.response?.data?.detail;
  if (msg) {
    if (Array.isArray(msg)) return msg.map((m: any) => m.msg || JSON.stringify(m)).join('; ');
    return String(msg);
  }
  if (e.code === 'ECONNABORTED') return '连接超时，请检查网络';
  if (!e.response) return '网络连接失败，请检查服务器状态';
  if (e.response.status === 413) return '文件过大，服务器拒绝';
  if (e.response.status === 500) return '服务器内部错误';
  return e.message || '上传失败';
}

// ==================== localStorage 清理 ====================

/**
 * 清理过期的或超量的分片上传断点续传记录。
 * 模块加载时在浏览器环境自动执行一次。
 */
function cleanupStaleUploadRecords(): void {
  const records: { key: string; timestamp: number }[] = [];

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith(LS_KEY_PREFIX)) {
      try {
        const data = JSON.parse(localStorage.getItem(key) || '');
        records.push({ key, timestamp: data.timestamp || 0 });
      } catch {
        localStorage.removeItem(key);
      }
    }
  }

  records.sort((a, b) => a.timestamp - b.timestamp);
  const now = Date.now();

  records.forEach((record, index) => {
    const isStale = now - record.timestamp > MAX_AGE_MS;
    const isOverflow = index < records.length - MAX_RECORDS;
    if (isStale || isOverflow) {
      localStorage.removeItem(record.key);
    }
  });
}

if (typeof window !== 'undefined') {
  cleanupStaleUploadRecords();
}

// ==================== 上传进度 Modal ====================

interface UploadProgressModalProps {
  file: File;
  /** [改进] 裁剪后保留的原始文件，随 multipart 上传供后端 orig_ 双存溯源 */
  originalFile?: File | null;
  entityType: 'doctor' | 'nurse' | 'technician' | 'admin' | 'specialty' | 'equipment';
  entityId: string;
  photoType: 'front' | 'side' | 'card' | 'image';
  onCancel: () => void;
  onComplete: (filePath: string) => void;
}

const UploadProgressModal: React.FC<UploadProgressModalProps> = ({
  file, originalFile, entityType, entityId, photoType, onCancel, onComplete,
}) => {
  const [progress, setProgress] = useState(0);
  const [uploaded, setUploaded] = useState(0);
  const [speed, setSpeed] = useState('--');
  const [status, setStatus] = useState<'uploading' | 'success' | 'error'>('uploading');
  const [errorMsg, setErrorMsg] = useState('');
  const [phase, setPhase] = useState<'preparing' | 'uploading' | 'merging'>('preparing');
  const cancelRef = useRef(false);
  const uploadIdRef = useRef<string | null>(null);
  const lastLoaded = useRef(0);
  const lastTime = useRef(Date.now());
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;
  const generationRef = useRef(0);

  const totalSize = useMemo(() => formatSize(file.size), [file.size]);
  const useChunked = file.size > CHUNK_SIZE;
  const totalChunks = useChunked ? Math.ceil(file.size / CHUNK_SIZE) : 1;

  const calcSpeed = (loaded: number) => {
    const now = Date.now();
    const elapsed = (now - lastTime.current) / 1000;
    if (elapsed > 0.3) {
      const bytesPerSec = (loaded - lastLoaded.current) / elapsed;
      setSpeed(bytesPerSec > 1024 * 1024
        ? (bytesPerSec / 1024 / 1024).toFixed(1) + ' MB/s'
        : (bytesPerSec / 1024).toFixed(1) + ' KB/s');
      lastLoaded.current = loaded;
      lastTime.current = now;
    }
  };

  const initUpload = async () => {
    const formData = new FormData();
    formData.append('entity_type', entityType);
    formData.append('entity_id', entityId);
    formData.append('photo_type', photoType);
    formData.append('file_name', file.name);
    formData.append('file_size', String(file.size));
    const initResp = await uploadApi.post('/upload/init', formData);
    return initResp.data.upload_id;
  };

  // ====== 核心上传逻辑（与原版一致，不修改） ======

  const startUpload = useCallback(async (gen?: number) => {
    cancelRef.current = false;
    const isStale = () => gen !== undefined && gen !== generationRef.current;

    if (!useChunked) {
      setPhase('uploading');
      const formData = new FormData();
      formData.append('file', file);
      // [改进] 前端裁剪照片后附带原始文件，后端以 orig_ 前缀双存供下载溯源
      if (originalFile) formData.append('original', originalFile);

      if (entityType === 'specialty' || entityType === 'equipment') {
        try {
          const initFormData = new FormData();
          initFormData.append('entity_type', entityType);
          initFormData.append('entity_id', entityId);
          initFormData.append('photo_type', photoType);
          initFormData.append('file_name', file.name);
          initFormData.append('file_size', String(file.size));
          const initResp = await uploadApi.post('/upload/init', initFormData);
          const uploadId: string = initResp.data.upload_id;
          const chunkTotal: number = initResp.data.total_chunks;
          const cs: number = initResp.data.chunk_size;

          for (let i = 0; i < chunkTotal; i++) {
            const start = i * cs;
            const end = Math.min(start + cs, file.size);
            const chunk = file.slice(start, end);
            const cf = new FormData();
            cf.append('file', chunk, `chunk_${i}`);
            await uploadApi.post(`/upload/${uploadId}/chunk/${i}`, cf);
          }
          const completeResp = await uploadApi.post(`/upload/${uploadId}/complete`);
          const data = completeResp.data;
          const fp = data.image_url || data.file_path;
          setProgress(100);
          setUploaded(file.size);
          setStatus('success');
          setTimeout(() => onCompleteRef.current(fp), 800);
        } catch (err: unknown) {
          const e = err as { code?: string; message?: string; response?: { status?: number; data?: { detail?: unknown } } };
          if (e.code === 'ERR_CANCELED' || e.code === 'ERR_ABORTED') return;
          setStatus('error');
          setErrorMsg(getErrMsg(e));
        }
        return;
      }

      const url = photoType === 'card'
        ? `/cards?entity_type=${entityType}&entity_id=${entityId}`
        : `/uploads/photo/${entityType}/${entityId}?photo_type=${photoType}`;

      try {
        const resp = await uploadApi.post(url, formData, {
          onUploadProgress: (e) => {
            if (!e.total) return;
            const pct = Math.round((e.loaded / e.total) * 100);
            setProgress(pct);
            setUploaded(e.loaded);
            calcSpeed(e.loaded);
          },
        });
        const data = resp.data;
        const fp = data.card_photo || data.file_path;
        setProgress(100);
        setUploaded(file.size);
        setStatus('success');
        setTimeout(() => onCompleteRef.current(fp), 800);
      } catch (err: unknown) {
        const e = err as { code?: string; message?: string; response?: { status?: number; data?: { detail?: unknown } } };
        if (e.code === 'ERR_CANCELED' || e.code === 'ERR_ABORTED') return;
        setStatus('error');
        setErrorMsg(getErrMsg(e));
      }
      return;
    }

    // 大文件：分片上传（含断点续传）
    try {
      const lsKey = LS_KEY_PREFIX + `${entityType}_${entityId}_${photoType}`;
      const saved = localStorage.getItem(lsKey);
      let uploadId: string;
      let receivedChunks: number[] = [];

      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (parsed.file_name === file.name && parsed.file_size === file.size) {
            uploadId = parsed.upload_id;
            setPhase('preparing');
            const statusResp = await uploadApi.get(`/upload/${uploadId}`);
            receivedChunks = statusResp.data.received_chunks || [];
          } else {
            localStorage.removeItem(lsKey);
            uploadId = await initUpload();
          }
        } catch {
          localStorage.removeItem(lsKey);
          uploadId = await initUpload();
        }
      } else {
        uploadId = await initUpload();
      }

      if (isStale()) return;
      uploadIdRef.current = uploadId;

      localStorage.setItem(lsKey, JSON.stringify({
        upload_id: uploadId, file_name: file.name, file_size: file.size,
        entity_type: entityType, entity_id: entityId, photo_type: photoType, timestamp: Date.now(),
      }));

      const total = totalChunks;
      let completed = receivedChunks.length;
      setPhase('uploading');

      for (let i = 0; i < total; i++) {
        if (cancelRef.current || isStale()) break;
        if (receivedChunks.includes(i)) {
          completed++;
          setProgress(Math.round((completed / total) * 100));
          setUploaded(Math.round((completed / total) * file.size));
          continue;
        }

        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, file.size);
        const chunk = file.slice(start, end);
        let ok = false;

        for (let retry = 0; retry <= MAX_RETRIES; retry++) {
          if (cancelRef.current || isStale()) break;
          try {
            const cf = new FormData();
            cf.append('file', chunk, `chunk_${i}`);
            await uploadApi.post(`/upload/${uploadId}/chunk/${i}`, cf, { timeout: 30000 });
            ok = true;
            completed++;
            const pct = Math.round((completed / total) * 100);
            setProgress(pct);
            setUploaded(Math.round((completed / total) * file.size));
            calcSpeed((completed / total) * file.size);
            break;
          } catch (err: unknown) {
            if (cancelRef.current || isStale()) break;
            if (retry < MAX_RETRIES) {
              await new Promise((r) => setTimeout(r, 1000 * (retry + 1)));
            } else {
              setErrorMsg(`分片 ${i + 1}/${total} 上传失败: ${getErrMsg(err as never)}`);
              setStatus('error');
              return;
            }
          }
        }
        if (!ok && !cancelRef.current && !isStale()) { setStatus('error'); return; }
      }

      if (cancelRef.current || isStale()) return;

      setPhase('merging');
      setProgress(99);
      const completeResp = await uploadApi.post(`/upload/${uploadId}/complete`);
      const data = completeResp.data;
      const fp = data.card_photo || data.file_path;
      // [改进] 上传完成后用响应里的 file_token 刷新本地图片访问令牌，避免刚上传的照片因令牌过期显示"文件已丢失"
      if (data.file_token) setFileToken(data.file_token);
      localStorage.removeItem(lsKey);
      setProgress(100);
      setUploaded(file.size);
      setStatus('success');
      setTimeout(() => onCompleteRef.current(fp), 800);
    } catch (err: unknown) {
      setStatus('error');
      setErrorMsg(getErrMsg(err as never));
    }
  }, [file, originalFile, entityType, entityId, photoType, useChunked, totalChunks]);

  useEffect(() => {
    generationRef.current++;
    const myGeneration = generationRef.current;
    startUpload(myGeneration).catch((err) => {
      setStatus('error');
      setErrorMsg(getErrMsg(err as never));
    });
    return () => {
      cancelRef.current = true;
      generationRef.current++;
    };
  }, [startUpload]);

  const handleCancelAction = () => {
    cancelRef.current = true;
    if (uploadIdRef.current) {
      uploadApi.delete(`/upload/${uploadIdRef.current}`).catch(() => {});
      localStorage.removeItem(LS_KEY_PREFIX + `${entityType}_${entityId}_${photoType}`);
    }
    onCancel();
  };

  const handleRetry = () => {
    setStatus('uploading');
    setErrorMsg('');
    cancelRef.current = false;
    startUpload();
  };

  const phaseLabel = phase === 'preparing' ? '准备中...'
    : phase === 'merging' ? '合并文件中...'
    : status === 'error' ? '上传失败'
    : status === 'success' ? '上传完成'
    : `上传分片 ${Math.min(Math.round(progress / 100 * totalChunks) + 1, totalChunks)}/${totalChunks}`;

  // [改进] 使用 Ant Design Modal + Progress 组件
  return (
    <Modal
      open
      onCancel={status === 'uploading' || status === 'success' ? undefined : handleCancelAction}
      footer={null}
      closable={status !== 'uploading'}
      maskClosable={false}
      centered
      width={400}
      title={
        <span>
          {useChunked ? '分片上传' : '上传照片'}
          {useChunked && <Tag style={{ marginLeft: 8, fontSize: 12 }}>断点续传</Tag>}
        </span>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <Text style={{ fontSize: 13, maxWidth: 240 }} ellipsis={{ tooltip: file.name }}>
            {file.name}
          </Text>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {formatSize(uploaded)} / {totalSize}
          </Text>
        </div>
        <Progress
          percent={progress}
          status={status === 'error' ? 'exception' : status === 'success' ? 'success' : 'active'}
          /* [改造 2026-09-19] 进度条色改引用变量（深色下自动提亮） */
          strokeColor={status === 'error' ? 'var(--danger)' : 'var(--accent)'}
          showInfo={false}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>{phaseLabel}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{status === 'uploading' ? speed : ''}</Text>
        </div>
      </div>

      {errorMsg && (
        <Alert message={errorMsg} type="error" showIcon style={{ marginBottom: 12, fontSize: 12 }} />
      )}

      {useChunked && status === 'uploading' && (
        <Alert
          message="大文件分片上传中，网络中断后可自动续传"
          type="info"
          showIcon
          style={{ marginBottom: 12, fontSize: 12 }}
        />
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        {status === 'success' ? (
          <Button type="primary" onClick={() => onCompleteRef.current('')}>完成</Button>
        ) : status === 'error' ? (
          <>
            <Button onClick={handleCancelAction}>取消</Button>
            <Button type="primary" danger onClick={handleRetry}>重试</Button>
          </>
        ) : (
          <Button onClick={handleCancelAction}>取消</Button>
        )}
      </div>
    </Modal>
  );
};

// ==================== 主组件 ====================

interface PhotoUploadProps {
  type: 'doctor' | 'nurse';
  employeeId: string;
  photoType: 'front' | 'side' | 'card';
  currentPhoto?: string | null;
  onUploadSuccess: (photoUrl: string) => void;
  onDeleteSuccess?: () => void;
  disabled?: boolean;
  /** [新增 2026-09-15] 是否允许删除已有照片；不传时沿用旧行为（随 disabled 取反）。
   *  人员照片的删除属「修改人员信息」（staff.edit）权限范畴，与「照片上传」权限分离控制 */
  canDelete?: boolean;
  /** [新增 2026-09-15] 禁用原因提示：disabled 时在组件内以 Alert 展示，
   *  用于说明为何不可上传（如「无照片上传权限」）并给出授权路径 */
  disabledHint?: string;
  label?: string;
  /** [改进] 裁剪宽高比（宽/高），如 3:4 传 0.75；设置后上传前弹出裁剪框（允许跳过直传原图） */
  cropAspect?: number;
}

const PhotoUpload: React.FC<PhotoUploadProps> = ({
  type, employeeId, photoType, currentPhoto, onUploadSuccess, onDeleteSuccess,
  disabled = false, canDelete, disabledHint, label, cropAspect,
}) => {
  // [新增 2026-09-15] 删除按钮可见性：未显式传入 canDelete 时保持「非 disabled 即可删除」的旧行为
  const canDeletePhoto = canDelete ?? !disabled;
  const { token } = useToken();
  const [preview, setPreview] = useState<string | null>(currentPhoto || null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);
  // [改进] 待裁剪文件 / 裁剪后保留的原始文件 / 原图预览源（orig_ 优先）
  const [cropperFile, setCropperFile] = useState<File | null>(null);
  const [originalFile, setOriginalFile] = useState<File | null>(null);
  const [viewSrc, setViewSrc] = useState('');
  // [改进] orig_ 候选 URL 列表与当前探测索引（扩展名与正式图可能不同，需逐级回退）
  const origCandidatesRef = useRef<string[]>([]);
  const origIndexRef = useRef(0);

  useEffect(() => {
    setPreview(currentPhoto || null);
  }, [currentPhoto]);

  const thumbUrl = getThumbnailUrl(preview);
  const originalUrl = getOriginalUrl(preview);

  // [改进] 查看原图时优先加载 orig_ 原始副本（多扩展名候选逐级探测）；耗尽后回退正式图
  useEffect(() => {
    if (showOriginal) {
      origCandidatesRef.current = getOriginalPreferredCandidates(preview);
      origIndexRef.current = 0;
      setViewSrc(origCandidatesRef.current[0] || originalUrl || '');
    }
  }, [showOriginal, preview, originalUrl]);

  const validateFile = (file: File): string | null => {
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp'];
    if (!allowedTypes.includes(file.type)) return '仅支持 JPG/PNG/WebP 格式的图片';
    const maxSize = 20 * 1024 * 1024;
    if (file.size > maxSize) return `文件大小 ${(file.size / 1024 / 1024).toFixed(2)}MB 超过限制，最大允许 20MB`;
    return null;
  };

  const validateResolution = (file: File): Promise<string | null> => {
    return new Promise((resolve) => {
      const img = document.createElement('img');
      const url = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(url);
        const minW = 700, minH = 700;
        if (img.width < minW || img.height < minH) {
          resolve(`分辨率 ${img.width}x${img.height} 不满足要求，最小需要 ${minW}x${minH}`);
        } else resolve(null);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      img.src = url;
    });
  };

  /** 文件选择处理：校验 → 弹裁剪框（如配置）或直接上传 */
  const handleFileSelected = async (file: File) => {
    // [修复 2026-09-15] 兜底拦截：禁用态（无「照片上传」权限）直接忽略，
    // 防止通过拖拽等旁路触发上传流程
    if (disabled) return false;
    setError(null);
    const v = validateFile(file);
    if (v) { setError(v); return false; }
    if (photoType !== 'card') {
      const r = await validateResolution(file);
      if (r) { setError(r); return false; }
    }
    // [改进] 配置了裁剪比例（正面/侧面照 3:4）时先弹裁剪框；允许跳过（取消则原图直传）
    if (cropAspect && photoType !== 'card') {
      setCropperFile(file);
      return false;
    }
    setUploadFile(file);
    setShowModal(true);
    return false; // 阻止 antd Upload 默认上传行为
  };

  /** 裁剪确认：主文件 = 裁剪图（统一 3:4），原文件保留随 original 字段上传供后端双存 */
  const handleCropConfirm = (blob: Blob) => {
    const src = cropperFile;
    if (!src) return;
    const cropped = new File([blob], `cropped_${src.name}`, { type: 'image/jpeg' });
    setOriginalFile(src);
    setCropperFile(null);
    setUploadFile(cropped);
    setShowModal(true);
  };

  /** 取消/跳过裁剪：允许直传原图 */
  const handleCropCancel = () => {
    const src = cropperFile;
    setCropperFile(null);
    setUploadFile(src);
    setShowModal(true);
  };

  const handleModalComplete = (filePath: string) => {
    setShowModal(false);
    setUploadFile(null);
    setOriginalFile(null);
    setPreview(filePath);
    onUploadSuccess(filePath);
  };

  const handleCancel = () => {
    setShowModal(false);
    setUploadFile(null);
    setOriginalFile(null);
  };

  const handleDelete = async () => {
    if (!preview || !onDeleteSuccess) return;
    try {
      if (photoType === 'card') {
        await onDeleteSuccess();
      } else {
        await uploadApi.delete(`/uploads/photo/${type}/${employeeId}/${photoType}`);
        setPreview(null);
        onDeleteSuccess();
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || '删除失败');
    }
  };

  /** 下载原图（优先 orig_ 原始副本，不存在则回退正式图） */
  const downloadPhoto = async () => {
    const url = originalUrl;
    if (!url) return;
    // [改进] 文件名后缀以数据库记录的真实路径为准（preview 含真实扩展名，如 .png），
    // 不再写死 .jpg，避免 PNG 原图被下载成 .jpg 导致格式不匹配。
    const realExt = preview ? (preview.slice(preview.lastIndexOf('.')) || '.jpg') : '.jpg';
    const baseName = `${type}_${employeeId}_${photoType}`;
    // [改进] 优先下载原始照片（orig_ 副本，多扩展名候选逐级探测）；旧数据无 orig_ 时回退正式图
    let downloadUrl = url;
    for (const cand of getOriginalPreferredCandidates(preview)) {
      try {
        const probe = await fetch(cand, { method: 'HEAD' });
        if (probe.ok) {
          downloadUrl = cand;
          break;
        }
      } catch { /* ignore */ }
    }
    try {
      const resp = await fetch(downloadUrl);
      if (!resp.ok) return;
      const blob = await resp.blob();
      // [改进] 下载扩展名以真实内容为准（原图可能是 PNG/WebP，而非正式图的 .jpg）
      const mimeExt: Record<string, string> = { 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp' };
      const downloadExt = mimeExt[blob.type] || realExt;
      // [修正 2026-09-22] 改用公共 downloadBlob：原实现缺 appendChild
      // （Firefox 下 click() 不触发下载），且 revoke 紧跟 click 之后。
      downloadBlob(blob, `${baseName}${downloadExt}`);
    } catch { /* ignore */ }
  };

  const getLabel = (): string => {
    if (label) return label;
    switch (photoType) {
      case 'front': return '正面形象照';
      case 'side': return '侧面形象照';
      case 'card': return '卡片照片';
      default: return '照片';
    }
  };

  return (
    <div>
      <div style={{ border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadius, padding: token.paddingMD }}>
        {/* 标题栏 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: token.marginMD }}>
          <Text strong style={{ fontSize: token.fontSize }}>{getLabel()}</Text>
          {/* [调整 2026-09-15] 删除按钮改由 canDeletePhoto 控制：人员照片删除属「修改人员信息」权限，
              与「照片上传」权限分开，可单独授予/回收（与后端 delete_photo 校验保持一致） */}
          {thumbUrl && onDeleteSuccess && canDeletePhoto && (
            <Button type="link" danger size="small" icon={<DeleteOutlined />} onClick={handleDelete}>
              删除
            </Button>
          )}
        </div>

        {/* 上传提示：无上传权限（disabled）时改为展示禁用原因与授权路径，避免用户反复点击无效 */}
        {disabled ? (
          <Alert
            message={disabledHint || '当前无上传权限，仅可查看/下载现有照片'}
            type="warning"
            showIcon
            style={{ marginBottom: token.marginMD, fontSize: token.fontSizeSM }}
          />
        ) : (
          <Alert
            message={`照片不大于20MB${photoType !== 'card' ? '，分辨率不小于700x700' : ''}，支持断点续传`}
            type="info"
            showIcon
            style={{ marginBottom: token.marginMD, fontSize: token.fontSizeSM }}
          />
        )}

        {/* 已上传预览 或 拖拽上传区 */}
        {thumbUrl ? (
          <div style={{ position: 'relative', marginBottom: token.marginMD }}>
            <SafeImage
              src={preview}
              alt={getLabel()}
              style={{ width: '100%', maxHeight: 500, objectFit: 'contain', borderRadius: token.borderRadius }}
            />
            <div
              style={{
                position: 'absolute',
                bottom: 0, left: 0, right: 0,
                background: 'linear-gradient(to top, rgba(0,0,0,0.6), transparent)',
                borderRadius: `0 0 ${token.borderRadius}px ${token.borderRadius}px`,
                display: 'flex',
                justifyContent: 'center',
                gap: 8,
                padding: '12px 8px 16px',
                opacity: 0,
                transition: 'opacity 0.3s',
              }}
              className="photo-upload-hover-actions"
            >
              {/* [调整 2026-09-15] 下载/查看原图对所有可见者开放；仅「更换照片」需上传权限，
                  使无「照片上传」权限的用户仍可查看与留存现有照片 */}
              <Button size="small" icon={<DownloadOutlined />} onClick={downloadPhoto} ghost>
                下载
              </Button>
              <Button size="small" icon={<EyeOutlined />} onClick={() => setShowOriginal(true)} ghost>
                查看原图
              </Button>
              {/* [改进] 通过隐藏的 Upload 触发文件选择 */}
              {!disabled && (
                <Button
                  size="small"
                  icon={<SwapOutlined />}
                  ghost
                  onClick={() => {
                    const hiddenInput = document.querySelector<HTMLInputElement>(
                      `#photo-upload-input-${type}-${photoType}`
                    );
                    hiddenInput?.click();
                  }}
                >
                  更换照片
                </Button>
              )}
            </div>
          </div>
        ) : (
          /* [改进] 拖拽上传区域 */
          <div
            style={{
              border: `2px dashed ${token.colorBorder}`,
              borderRadius: token.borderRadius,
              padding: '40px 16px',
              textAlign: 'center',
              cursor: disabled ? 'not-allowed' : 'pointer',
              transition: 'border-color 0.3s',
            }}
            className="photo-upload-dragger"
            onClick={() => {
              if (!disabled) {
                const hiddenInput = document.querySelector<HTMLInputElement>(
                  `#photo-upload-input-${type}-${photoType}`
                );
                hiddenInput?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              // [修复 2026-09-15] 无上传权限时不显示拖拽高亮，避免误导可上传
              // [改造 2026-09-19] 色值改引用变量（深色下边框与高亮自动适配）
              if (!disabled) e.currentTarget.style.borderColor = 'var(--accent)';
            }}
            onDragLeave={(e) => { e.currentTarget.style.borderColor = 'var(--line-soft)'; }}
            onDrop={(e) => {
              e.preventDefault();
              e.currentTarget.style.borderColor = 'var(--line-soft)';
              // [修复 2026-09-15] 禁用态（无「照片上传」权限）忽略拖拽，与点击/文件选择框拦截保持一致
              if (disabled) return;
              const files = e.dataTransfer.files;
              if (files.length > 0) handleFileSelected(files[0]);
            }}
          >
            <InboxOutlined style={{ fontSize: 36, color: 'var(--text-3)' }} />
            {/* [调整 2026-09-15] 无上传权限时明确提示不可上传及授权路径，不留「可点但无反应」的困惑 */}
            <p style={{ marginTop: 8, color: 'var(--text-3)' }}>
              {disabled ? '暂无可上传权限' : '点击或拖拽上传照片'}
            </p>
            <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>
              {disabled ? '如需上传请联系管理员授权' : '支持 JPG/PNG/WebP 格式'}
            </p>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <Alert message={error} type="error" showIcon closable onClose={() => setError(null)} style={{ marginTop: 12 }} />
        )}

        {/* 隐藏的文件输入 */}
        <input
          id={`photo-upload-input-${type}-${photoType}`}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFileSelected(file);
            e.target.value = '';
          }}
          style={{ display: 'none' }}
          disabled={disabled}
        />
      </div>

      {/* 上传进度 Modal（携带裁剪后保留的原始文件，供后端 orig_ 双存） */}
      {showModal && uploadFile && (
        <UploadProgressModal
          file={uploadFile}
          originalFile={originalFile}
          entityType={type}
          entityId={employeeId}
          photoType={photoType}
          onCancel={handleCancel}
          onComplete={handleModalComplete}
        />
      )}

      {/* [改进] 照片裁剪 Modal（配置了 cropAspect 时弹出，允许跳过直传原图） */}
      {cropperFile && cropAspect && (
        <PhotoCropper
          file={cropperFile}
          aspect={cropAspect}
          onConfirm={handleCropConfirm}
          onCancel={handleCropCancel}
        />
      )}

      {/* [改进] 原图预览 Modal */}
      <Modal
        open={showOriginal && !!originalUrl}
        onCancel={() => setShowOriginal(false)}
        footer={null}
        centered
        width="90vw"
        styles={{ body: { padding: 8, display: 'flex', justifyContent: 'center' } }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <Image
            src={viewSrc || ''}
            alt={getLabel()}
            style={{ maxWidth: '100%', maxHeight: '80vh', objectFit: 'contain' }}
            preview={false}
            onError={() => {
              // [改进] 逐级探测 orig_ 候选（扩展名可能与正式图不同）；耗尽后回退正式图
              const cands = origCandidatesRef.current;
              const next = origIndexRef.current + 1;
              if (next < cands.length) {
                origIndexRef.current = next;
                setViewSrc(cands[next]);
              } else {
                setViewSrc(originalUrl || '');
              }
            }}
          />
          <Space style={{ marginTop: 12 }}>
            <Button icon={<DownloadOutlined />} onClick={downloadPhoto}>下载原图</Button>
            <Button onClick={() => setShowOriginal(false)}>关闭</Button>
          </Space>
        </div>
      </Modal>

      {/* Hover 效果 CSS-in-JS */}
      <style>{`
        .photo-upload-hover-actions:hover { opacity: 1 !important; }
        .photo-upload-dragger:hover { border-color: var(--accent) !important; }
      `}</style>
    </div>
  );
};

export default PhotoUpload;
