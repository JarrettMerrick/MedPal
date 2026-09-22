// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 科室新增/编辑表单（支持特色技术+设备动态区块 + 图片管理）。
 * [改进] 手写 Tailwind form → Ant Design Card/Input/Select/Button/Modal.confirm
 * 业务逻辑完整保留：分片上传、待上传暂存、sort_order 对齐、isRestricted 限制
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { Card, Input, Select, Button, Alert, Typography, Tag, App, theme, Checkbox } from 'antd';
import { PlusOutlined, DeleteOutlined, UploadOutlined } from '@ant-design/icons';
import { getDepartment, createDepartment, updateDepartment, uploadSpecialtyImage, deleteSpecialtyImage, updateSpecialtyImageCaption, uploadEquipmentImage, deleteEquipmentImage, updateEquipmentImageCaption, uploadGroupPhoto, deleteGroupPhoto } from '../../api/departments';
import { useAuth } from '../../contexts/AuthContext';
import { getOriginalUrl } from '../../utils/imageUtils';
import SafeImage from '../../components/SafeImage';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import { uploadApi } from '../../api/client';
import type { DepartmentSpecialty, SpecialtyImage, DepartmentEquipment, EquipmentImage } from '../../types/department';
// [修复 2026-09-02] P4: 导入统一错误处理函数
import { getErrorMessage } from '../../utils/format';

const { TextArea } = Input;
const { Text, Title } = Typography;
const { useToken } = theme;

interface PendingImage { file: File; preview: string; caption: string; }
type SpecWithPending = DepartmentSpecialty & { _key?: number; _pendingImages?: PendingImage[] };
type EquipWithPending = DepartmentEquipment & { _key?: number; _pendingImages?: PendingImage[] };

const CATEGORY_OPTIONS = [
  { value: '临床专科', label: '临床专科（医生管理使用）' },
  { value: '护理病区', label: '护理病区（护士管理使用）' },
  { value: '行政科室', label: '行政科室（行政人员管理使用）' },
];

// [修复 2026-09-01] 新增工种选项，用于配置混合科室允许的工种
const WORK_TYPE_OPTIONS = [
  { value: 'doctor', label: '医生' },
  { value: 'nurse', label: '护士' },
  { value: 'technician', label: '技师' },
  { value: 'admin', label: '行政' },
];

// [修复 2026-09-02] P2: 提取高频内联 style 为常量，避免每次渲染创建新对象
const STYLES = {
  formItem: { marginBottom: 16 } as React.CSSProperties,
  label: { fontSize: 12, display: 'block' as const, marginBottom: 4 } as React.CSSProperties,
  input: { marginTop: 4, width: '100%' } as React.CSSProperties,
  sectionTitle: { marginBottom: 12, paddingTop: 16, borderTop: '1px solid var(--line-softer)' } as React.CSSProperties,
  emptyText: { display: 'block' as const, textAlign: 'center' as const, padding: '16px 0' } as React.CSSProperties,
  cardItem: { marginBottom: 12, background: 'var(--neu-page-bg)', position: 'relative' as const } as React.CSSProperties,
  // [修复 2026-09-05] 补充缺失的 cardContent 样式（TS2339）：用于卡片内单个字段行（名称/简介等）
  cardContent: { marginBottom: 12 } as React.CSSProperties,
  gridImages: { display: 'grid' as const, gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 } as React.CSSProperties,
  image: { width: '100%', height: 250, objectFit: 'contain' as const } as React.CSSProperties,
  imageCaption: { padding: '4px 6px' } as React.CSSProperties,
  addButton: { color: 'var(--ok)', borderColor: 'var(--ok)' } as React.CSSProperties,
  restrictedText: { color: 'var(--text-3)' } as React.CSSProperties,
};

const DepartmentForm: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id && id !== 'new';
  const { message, modal } = App.useApp();
  const { token } = useToken();

  // [改进] 获取来源页面URL，用于返回按钮恢复原始状态
  const returnTo = (location.state as any)?.returnTo as string | undefined;

  const [name, setName] = useState('');
  const [category, setCategory] = useState('临床专科');
  // [修复 2026-09-01] 新增 allowedWorkTypes 状态，支持混合科室配置
  const [allowedWorkTypes, setAllowedWorkTypes] = useState<string[]>([]);
  const [description, setDescription] = useState('');
  const [groupPhoto, setGroupPhoto] = useState('');
  const [specialties, setSpecialties] = useState<SpecWithPending[]>([]);
  const [equipments, setEquipments] = useState<EquipWithPending[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadingSpec, setUploadingSpec] = useState<number | null>(null);
  const [uploadingEquip, setUploadingEquip] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRefs = useRef<{ [key: number]: HTMLInputElement }>({});
  const equipFileInputRefs = useRef<{ [key: number]: HTMLInputElement }>({});
  const { user } = useAuth();
  const isRestricted = isEdit && user?.department_scope === 'managed';
  const pendingUrlsRef = useRef<Set<string>>(new Set());
  // [修复] 记录已保存图片备注的"上次持久化值"，onBlur 时比对避免无变化也发请求
  const savedCaptionRef = useRef<Record<number, string>>({});

  const trackPendingUrl = useCallback((url: string) => { pendingUrlsRef.current.add(url); }, []);
  const untrackPendingUrl = useCallback((url: string) => { pendingUrlsRef.current.delete(url); URL.revokeObjectURL(url); }, []);

  useEffect(() => { return () => { pendingUrlsRef.current.forEach(u => URL.revokeObjectURL(u)); pendingUrlsRef.current.clear(); }; }, []);

  useEffect(() => {
    if (isEdit && id) {
      getDepartment(Number(id)).then((data) => {
        setName(data.name); setCategory(data.category || '临床专科');
        setDescription(data.description || ''); setGroupPhoto(data.group_photo || '');
        // [修复 2026-09-01] 加载 allowed_work_types 字段，解析为数组
        setAllowedWorkTypes(data.allowed_work_types ? data.allowed_work_types.split(',').map(s => s.trim()) : []);
        setSpecialties((data.specialties || []).map((s, i) => ({ ...s, _key: i })));
        setEquipments((data.equipments || []).map((e, i) => ({ ...e, _key: i })));
      });
    }
  }, [id, isEdit]);

  const addSpecialty = () => setSpecialties([...specialties, { name: '', detail: '', sort_order: specialties.length, images: [], _pendingImages: [], _key: Date.now() }]);
  const removeSpecialty = (idx: number) => { specialties[idx]._pendingImages?.forEach(p => untrackPendingUrl(p.preview)); setSpecialties(specialties.filter((_, i) => i !== idx)); };
  const updateSpecialty = (idx: number, field: keyof DepartmentSpecialty, value: string | number) => { const u = [...specialties]; (u[idx] as any)[field] = value; setSpecialties(u); };

  const addEquipment = () => setEquipments([...equipments, { name: '', model: '', function_description: '', features: '', sort_order: equipments.length, images: [], _pendingImages: [], _key: Date.now() }]);
  const removeEquipment = (idx: number) => { equipments[idx]._pendingImages?.forEach(p => untrackPendingUrl(p.preview)); setEquipments(equipments.filter((_, i) => i !== idx)); };
  const updateEquipment = (idx: number, field: keyof DepartmentEquipment, value: string | number) => { const u = [...equipments]; (u[idx] as any)[field] = value; setEquipments(u); };

  // [修复] 已保存的特色技术图片备注：onChange 实时更新本地 state（保证输入框响应），
  // onBlur 时调用后端 API 持久化。原代码 onChange 只有一句注释、什么都没做，
  // 导致已保存图片备注无法二次修改。
  const updateSavedSpecImageCaption = (idx: number, img: SpecialtyImage, value: string) => {
    const u = [...specialties]; const imgs = u[idx].images;
    if (imgs) { const i = imgs.findIndex(im => im.id === img.id); if (i >= 0) imgs[i].caption = value; }
    setSpecialties(u);
  };
  const saveSpecImageCaption = async (img: SpecialtyImage) => {
    if (!id || !img.id || !img.specialty_id) return;
    const newCaption = img.caption || '';
    if (savedCaptionRef.current[img.id] === newCaption) return; // 无变化不请求
    try {
      await updateSpecialtyImageCaption(Number(id), img.specialty_id, img.id, newCaption);
      savedCaptionRef.current[img.id] = newCaption;
      message.success('备注已更新');
    } catch (err) {
      message.error(getErrorMessage(err, '备注更新失败'));
    }
  };

  // [修复] 已保存的设备图片备注：同上逻辑
  const updateSavedEquipImageCaption = (idx: number, img: EquipmentImage, value: string) => {
    const u = [...equipments]; const imgs = u[idx].images;
    if (imgs) { const i = imgs.findIndex(im => im.id === img.id); if (i >= 0) imgs[i].caption = value; }
    setEquipments(u);
  };
  const saveEquipImageCaption = async (img: EquipmentImage) => {
    if (!id || !img.id || !img.equipment_id) return;
    const newCaption = img.caption || '';
    if (savedCaptionRef.current[img.id] === newCaption) return;
    try {
      await updateEquipmentImageCaption(Number(id), img.equipment_id, img.id, newCaption);
      savedCaptionRef.current[img.id] = newCaption;
      message.success('备注已更新');
    } catch (err) {
      message.error(getErrorMessage(err, '备注更新失败'));
    }
  };

  // 上传特色技术图片（分片上传保留）
  const handleImageUpload = async (specIdx: number, specId: number | undefined) => {
    const input = fileInputRefs.current[specIdx]; const file = input?.files?.[0]; if (!file) return; setError(null);
    if (id && specId) {
      setUploadingSpec(specIdx);
      try {
        const fd = new FormData(); fd.append('entity_type', 'specialty'); fd.append('entity_id', String(specId)); fd.append('photo_type', 'image'); fd.append('file_name', file.name); fd.append('file_size', String(file.size));
        const initR = await uploadApi.post('/upload/init', fd).then(r => r.data); const uploadId: string = initR.upload_id;
        for (let i = 0; i < initR.total_chunks; i++) {
          const start = i * initR.chunk_size; const chunk = file.slice(start, Math.min(start + initR.chunk_size, file.size)); const cf = new FormData(); cf.append('file', chunk, `chunk_${i}`);
          await uploadApi.post(`/upload/${uploadId}/chunk/${i}`, cf);
        }
        const compR = await uploadApi.post(`/upload/${uploadId}/complete`).then(r => r.data);
        const newImg: SpecialtyImage = { id: compR.image_id, specialty_id: specId, image_url: compR.image_url, caption: file.name.split('.')[0], sort_order: 0 };
        const u = [...specialties]; if (!u[specIdx].images) u[specIdx].images = []; (u[specIdx].images as SpecialtyImage[]).push(newImg); setSpecialties(u); input.value = '';
      } catch (err: unknown) { setError((err as any)?.response?.data?.detail || '上传失败'); } finally { setUploadingSpec(null); }
    } else {
      const url = URL.createObjectURL(file); trackPendingUrl(url); const u = [...specialties];
      if (!u[specIdx]._pendingImages) u[specIdx]._pendingImages = []; u[specIdx]._pendingImages!.push({ file, preview: url, caption: '' }); setSpecialties(u); input.value = '';
    }
  };

  const handleDeleteImage = async (specIdx: number, img: SpecialtyImage) => {
    if (!id) return;
    try { await deleteSpecialtyImage(Number(id), img.specialty_id, img.id); const u = [...specialties]; u[specIdx].images = (u[specIdx].images || []).filter(i => i.id !== img.id); setSpecialties(u); }
    catch (err: unknown) { message.error((err as any)?.response?.data?.detail || '删除失败'); }
  };
  const handleDeletePendingImage = (specIdx: number, pIdx: number) => { const u = [...specialties]; const p = u[specIdx]._pendingImages || []; untrackPendingUrl(p[pIdx].preview); u[specIdx]._pendingImages = p.filter((_, i) => i !== pIdx); setSpecialties(u); };
  const updatePendingImageCaption = (specIdx: number, pIdx: number, caption: string) => { const u = [...specialties]; (u[specIdx]._pendingImages || [])[pIdx].caption = caption; setSpecialties(u); };

  // 上传设备图片（分片上传保留）
  const handleEquipmentImageUpload = async (equipIdx: number, equipId: number | undefined) => {
    const input = equipFileInputRefs.current[equipIdx]; const file = input?.files?.[0]; if (!file) return; setError(null);
    if (id && equipId) {
      setUploadingEquip(equipIdx);
      try {
        const fd = new FormData(); fd.append('entity_type', 'equipment'); fd.append('entity_id', String(equipId)); fd.append('photo_type', 'image'); fd.append('file_name', file.name); fd.append('file_size', String(file.size));
        const initR = await uploadApi.post('/upload/init', fd).then(r => r.data); const uploadId: string = initR.upload_id;
        for (let i = 0; i < initR.total_chunks; i++) {
          const start = i * initR.chunk_size; const chunk = file.slice(start, Math.min(start + initR.chunk_size, file.size)); const cf = new FormData(); cf.append('file', chunk, `chunk_${i}`);
          await uploadApi.post(`/upload/${uploadId}/chunk/${i}`, cf);
        }
        const compR = await uploadApi.post(`/upload/${uploadId}/complete`).then(r => r.data);
        const newImg: EquipmentImage = { id: compR.image_id, equipment_id: equipId, image_url: compR.image_url, caption: file.name.split('.')[0], sort_order: 0 };
        const u = [...equipments]; if (!u[equipIdx].images) u[equipIdx].images = []; (u[equipIdx].images as EquipmentImage[]).push(newImg); setEquipments(u); input.value = '';
      } catch (err: unknown) { setError((err as any)?.response?.data?.detail || '上传失败'); } finally { setUploadingEquip(null); }
    } else {
      const url = URL.createObjectURL(file); trackPendingUrl(url); const u = [...equipments];
      if (!u[equipIdx]._pendingImages) u[equipIdx]._pendingImages = []; u[equipIdx]._pendingImages!.push({ file, preview: url, caption: '' }); setEquipments(u); input.value = '';
    }
  };
  const handleDeleteEquipmentImage = async (equipIdx: number, img: EquipmentImage) => {
    if (!id) return;
    try { await deleteEquipmentImage(Number(id), img.equipment_id, img.id); const u = [...equipments]; u[equipIdx].images = (u[equipIdx].images || []).filter(i => i.id !== img.id); setEquipments(u); }
    catch (err: unknown) { message.error((err as any)?.response?.data?.detail || '删除失败'); }
  };
  const handleDeletePendingEquipImage = (equipIdx: number, pIdx: number) => { const u = [...equipments]; const p = u[equipIdx]._pendingImages || []; untrackPendingUrl(p[pIdx].preview); u[equipIdx]._pendingImages = p.filter((_, i) => i !== pIdx); setEquipments(u); };
  const updatePendingEquipImageCaption = (equipIdx: number, pIdx: number, caption: string) => { const u = [...equipments]; (u[equipIdx]._pendingImages || [])[pIdx].caption = caption; setEquipments(u); };

  const handleSubmit = async () => {
    if (!name.trim()) { message.warning('请输入科室名称'); return; }
    setLoading(true);
    try {
      const validSpecialties = specialties.filter(s => s.name.trim());
      const validEquipments = equipments.filter(e => e.name.trim());
      // [修复 2026-09-01] 提交时将 allowedWorkTypes 数组转换为逗号分隔字符串
      const allowedWorkTypesStr = allowedWorkTypes.length > 0 ? allowedWorkTypes.join(',') : null;
      const payload: Record<string, unknown> = {
        name: name.trim(), category, description: description.trim(), group_photo: groupPhoto.trim() || null,
        allowed_work_types: allowedWorkTypesStr,
        specialties: validSpecialties.map((s, i) => ({ ...(s.id ? { id: s.id } : {}), name: s.name, detail: s.detail || '', sort_order: i })),
        equipments: validEquipments.map((e, i) => ({ ...(e.id ? { id: e.id } : {}), name: e.name, model: e.model || '', function_description: e.function_description || '', features: e.features || '', sort_order: i })),
      };
      let result;
      if (isEdit) result = await updateDepartment(Number(id), payload as Parameters<typeof updateDepartment>[1]);
      else result = await createDepartment(payload as Parameters<typeof createDepartment>[0]);
      // 上传暂存图片
      if (result?.specialties) {
        const sorted = [...result.specialties].sort((a: any, b: any) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        for (let i = 0; i < validSpecialties.length; i++) {
          const pending = validSpecialties[i]._pendingImages;
          if (pending) { const spec = sorted[i]; if (spec?.id != null) { for (const p of pending) { try { await uploadSpecialtyImage(result.id, spec.id, p.file, p.caption); } catch { /* ignore */ } } } }
        }
      }
      if (result?.equipments) {
        const sorted = [...result.equipments].sort((a: any, b: any) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        for (let i = 0; i < validEquipments.length; i++) {
          const pending = validEquipments[i]._pendingImages;
          if (pending) { const equip = sorted[i]; if (equip?.id != null) { for (const p of pending) { try { await uploadEquipmentImage(result.id, equip.id, p.file, p.caption); } catch { /* ignore */ } } } }
        }
      }
      pendingUrlsRef.current.forEach(u => URL.revokeObjectURL(u)); pendingUrlsRef.current.clear();
      navigate(returnTo || '/departments');
    } catch (err: unknown) { message.error((err as any)?.response?.data?.detail || '操作失败'); }
    finally { setLoading(false); }
  };

  // ========== 渲染 ==========
  // [修复] renderImageGrid 增加 onCaptionChange（实时更新本地 state）与
  // onCaptionSave（onBlur 持久化到后端），修复已保存图片备注无法二次修改的问题。
  const renderImageGrid = (
    images: (SpecialtyImage | EquipmentImage)[],
    onDelete: (img: any) => void,
    onCaptionChange: (img: any, value: string) => void,
    onCaptionSave: (img: any) => void,
  ) => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: token.marginMD, marginBottom: token.marginSM }}>
      {images.map(img => (
        <div key={img.id} style={{ border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadius, overflow: 'hidden', background: token.colorBgContainer }}>
          <div className="df-img-wrap" style={{ position: 'relative' }}>
            <SafeImage src={img.image_url} alt={img.caption || '图片'} style={{ width: '100%', height: 250, objectFit: 'contain', background: token.colorFillQuaternary }} />
            <div className="df-img-actions" style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)', opacity: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: token.marginSM, borderRadius: `0 0 ${token.borderRadius}px ${token.borderRadius}px` }}>
              <Button size="small" ghost href={getOriginalUrl(img.image_url) || ''} download>下载</Button>
              <Button size="small" danger ghost onClick={() => onDelete(img)}>删除</Button>
            </div>
          </div>
          <div style={{ padding: '4px 6px' }}>
            <Input size="small" maxLength={20} value={img.caption || ''} placeholder="备注（最多20字）"
              onChange={(e) => { const v = e.target.value; if (v.length <= 20) onCaptionChange(img, v); }}
              onBlur={() => onCaptionSave(img)} />
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <PageContainer maxWidth={800}>
      <PageHeader
        title={isEdit ? '编辑科室' : '新增科室'}
        onBack={() => navigate(returnTo || '/departments')}
      />

      <Card>
        {/* 基本信息 */}
        <Title level={5} style={STYLES.formItem}>基本信息</Title>
        <div style={STYLES.formItem}>
          <Text type="secondary" style={STYLES.label}>
            科室名称 {isRestricted ? <span style={{ color: 'var(--text-3)' }}>(仅管理员可修改)</span> : '*'}
          </Text>
          <Input value={name} onChange={e => setName(e.target.value)} readOnly={isRestricted} placeholder={isRestricted ? '仅管理员可修改' : '请输入科室名称'} style={isRestricted ? { background: 'var(--neu-page-bg)', color: 'var(--text-3)' } : undefined} />
        </div>
        <div style={STYLES.formItem}>
          <Text type="secondary" style={STYLES.label}>
            科室分类 {isRestricted ? <span style={STYLES.restrictedText}>(仅管理员可修改)</span> : ''}
          </Text>
          <Select value={category} onChange={setCategory} disabled={isRestricted} options={CATEGORY_OPTIONS} style={{ width: '100%' }} />
        </div>
        {/* [修复 2026-09-01] 新增允许的工种配置，支持混合科室 */}
        <div style={STYLES.formItem}>
          <Text type="secondary" style={STYLES.label}>
            允许的工种（可选）
          </Text>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            不选则按科室分类默认规则；选择后只允许列表中的工种人员加入该科室
          </Text>
          <Checkbox.Group
            value={allowedWorkTypes}
            onChange={setAllowedWorkTypes}
            disabled={isRestricted}
            options={WORK_TYPE_OPTIONS}
          />
        </div>
        <div style={STYLES.formItem}>
          <Text type="secondary" style={STYLES.label}>科室介绍</Text>
          <TextArea value={description} onChange={e => setDescription(e.target.value)} rows={4} placeholder="请输入科室介绍" />
        </div>

        {/* 科室合照 */}
        <div style={STYLES.formItem}>
          <Text type="secondary" style={STYLES.label}>科室合照</Text>
          {groupPhoto && (
            <div style={{ marginBottom: 8, position: 'relative', display: 'inline-block' }} className="df-img-wrap">
              <SafeImage src={groupPhoto} alt="科室合照" style={{ maxWidth: 300, borderRadius: token.borderRadius, border: `1px solid ${token.colorBorder}` }} hideOnError />
              <Button type="text" danger size="small" className="df-img-btn" style={{ position: 'absolute', top: 4, right: 4 }}
                onClick={() => {
                  if (!id) return;
                  modal.confirm({ title: '确定要删除科室合照吗？', onOk: async () => { try { await deleteGroupPhoto(Number(id)); setGroupPhoto(''); } catch (err) { message.error(getErrorMessage(err, '删除失败')); } } });
                }}>×</Button>
            </div>
          )}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: token.marginXS, padding: `${token.paddingXS}px ${token.paddingMD}px`, background: token.colorPrimary, color: token.colorTextLightSolid, borderRadius: token.borderRadius, cursor: 'pointer', fontSize: token.fontSizeSM }}>
            <UploadOutlined /> 上传合照
            <input type="file" accept="image/jpeg,image/png,image/webp" hidden
              onChange={async e => {
                const file = e.target.files?.[0]; if (!file || !id) return;
                try { const r = await uploadGroupPhoto(Number(id), file); setGroupPhoto(r.group_photo); } catch (err) { message.error(getErrorMessage(err, '上传失败')); }
              }} />
          </label>
        </div>

        {/* 特色技术 */}
        <Title level={5} style={{ ...STYLES.sectionTitle, marginTop: 24 }}>科室特色技术</Title>
        {specialties.length === 0 && <Text type="secondary" style={STYLES.emptyText}>暂无特色技术</Text>}
        {specialties.map((spec, idx) => {
          const specId = spec.id; const images = spec.images || []; const pending = spec._pendingImages || [];
          const totalImages = images.length + pending.length;
          return (
            <Card key={spec._key ?? spec.id ?? idx} size="small" style={STYLES.cardItem}
              extra={<Button type="text" danger icon={<DeleteOutlined />} size="small" onClick={() => removeSpecialty(idx)} />}>
              <div style={STYLES.cardContent}>
                <Text type="secondary" style={{ fontSize: 12 }}>技术名称 *</Text>
                <Input value={spec.name} onChange={e => updateSpecialty(idx, 'name', e.target.value)} placeholder="请输入特色技术名称" style={STYLES.input} required />
              </div>
              <div style={STYLES.cardContent}>
                <Text type="secondary" style={{ fontSize: 12 }}>详细简介</Text>
                <TextArea value={spec.detail} onChange={e => updateSpecialty(idx, 'detail', e.target.value)} rows={2} placeholder="请输入详细简介" style={STYLES.input} />
              </div>
              {/* 图片区 */}
              <div style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Text style={{ fontSize: token.fontSizeSM, color: token.colorTextSecondary }}>技术图片（{totalImages}/6）{!specId && pending.length > 0 && <Text type="warning" style={{ fontSize: token.fontSizeSM }}>（保存后自动上传）</Text>}</Text>
                  {totalImages < 6 && (
                    <Button size="small" type="link" loading={uploadingSpec === idx} onClick={() => fileInputRefs.current[idx]?.click()}>+ 上传图片</Button>
                  )}
                </div>
                {images.length > 0 && renderImageGrid(images, (img) => handleDeleteImage(idx, img), (img, v) => updateSavedSpecImageCaption(idx, img, v), (img) => saveSpecImageCaption(img))}
                {pending.length > 0 && (
                  <div style={STYLES.gridImages}>
                    {pending.map((p, pIdx) => (
                      <div key={`p-${pIdx}`} style={{ border: `2px dashed ${token.colorWarning}`, borderRadius: token.borderRadius, overflow: 'hidden', background: token.colorWarningBg }}>
                        <div style={{ position: 'relative' }}><img src={p.preview} alt="待上传" style={{ width: '100%', height: 250, objectFit: 'contain', background: token.colorFillQuaternary }} /><Tag color="gold" style={{ position: 'absolute', top: token.marginXS, right: token.marginXS, fontSize: token.fontSizeSM }}>待上传</Tag></div>
                        <div style={{ padding: '4px 6px', display: 'flex', gap: 4 }}>
                          <Input size="small" maxLength={20} value={p.caption} onChange={e => { if (e.target.value.length <= 20) updatePendingImageCaption(idx, pIdx, e.target.value); }} placeholder="备注（最多20字）" />
                          <Button size="small" danger type="text" onClick={() => handleDeletePendingImage(idx, pIdx)}>删除</Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <input ref={el => { if (el) fileInputRefs.current[idx] = el; }} type="file" accept="image/jpeg,image/png,image/webp" onChange={() => handleImageUpload(idx, specId)} hidden />
              </div>
            </Card>
          );
        })}
        <Button block type="dashed" icon={<PlusOutlined />} onClick={addSpecialty} style={STYLES.addButton}>添加特色技术</Button>

        {/* 特色设备 */}
        <Title level={5} style={{ ...STYLES.sectionTitle, marginTop: 32 }}>科室特色设备</Title>
        {equipments.length === 0 && <Text type="secondary" style={STYLES.emptyText}>暂无特色设备</Text>}
        {equipments.map((equip, idx) => {
          const equipId = equip.id; const images = equip.images || []; const pending = equip._pendingImages || [];
          const totalImages = images.length + pending.length;
          return (
            <Card key={equip._key ?? equip.id ?? idx} size="small" style={STYLES.cardItem}
              extra={<Button type="text" danger icon={<DeleteOutlined />} size="small" onClick={() => removeEquipment(idx)} />}>
              <div style={STYLES.cardContent}>
                <Text type="secondary" style={{ fontSize: 12 }}>设备名称 *</Text>
                <Input value={equip.name} onChange={e => updateEquipment(idx, 'name', e.target.value)} placeholder="请输入设备名称" style={STYLES.input} required />
              </div>
              <div style={STYLES.cardContent}>
                <Text type="secondary" style={{ fontSize: 12 }}>设备型号</Text>
                <Input value={equip.model} onChange={e => updateEquipment(idx, 'model', e.target.value)} placeholder="请输入设备型号" style={STYLES.input} />
              </div>
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>功能描述</Text>
                <TextArea value={equip.function_description} onChange={e => updateEquipment(idx, 'function_description', e.target.value)} rows={2} placeholder="请输入功能描述" style={{ marginTop: 4 }} />
              </div>
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>设备特点</Text>
                <TextArea value={equip.features} onChange={e => updateEquipment(idx, 'features', e.target.value)} rows={2} placeholder="请输入设备特点" style={{ marginTop: 4 }} />
              </div>
              {/* 图片区 */}
              <div style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Text style={{ fontSize: token.fontSizeSM, color: token.colorTextSecondary }}>设备图片（{totalImages}/6）{!equipId && pending.length > 0 && <Text type="warning" style={{ fontSize: token.fontSizeSM }}>（保存后自动上传）</Text>}</Text>
                  {totalImages < 6 && <Button size="small" type="link" loading={uploadingEquip === idx} onClick={() => equipFileInputRefs.current[idx]?.click()}>+ 上传图片</Button>}
                </div>
                {images.length > 0 && renderImageGrid(images, (img) => handleDeleteEquipmentImage(idx, img), (img, v) => updateSavedEquipImageCaption(idx, img, v), (img) => saveEquipImageCaption(img))}
                {pending.length > 0 && (
                  <div style={STYLES.gridImages}>
                    {pending.map((p, pIdx) => (
                      <div key={`pe-${pIdx}`} style={{ border: `2px dashed ${token.colorWarning}`, borderRadius: token.borderRadius, overflow: 'hidden', background: token.colorWarningBg }}>
                        <div style={{ position: 'relative' }}><img src={p.preview} alt="待上传" style={{ width: '100%', height: 250, objectFit: 'contain', background: token.colorFillQuaternary }} /><Tag color="gold" style={{ position: 'absolute', top: token.marginXS, right: token.marginXS, fontSize: token.fontSizeSM }}>待上传</Tag></div>
                        <div style={{ padding: '4px 6px', display: 'flex', gap: 4 }}>
                          <Input size="small" maxLength={20} value={p.caption} onChange={e => { if (e.target.value.length <= 20) updatePendingEquipImageCaption(idx, pIdx, e.target.value); }} placeholder="备注（最多20字）" />
                          <Button size="small" danger type="text" onClick={() => handleDeletePendingEquipImage(idx, pIdx)}>删除</Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <input ref={el => { if (el) equipFileInputRefs.current[idx] = el; }} type="file" accept="image/jpeg,image/png,image/webp" onChange={() => handleEquipmentImageUpload(idx, equipId)} hidden />
              </div>
            </Card>
          );
        })}
        <Button block type="dashed" icon={<PlusOutlined />} onClick={addEquipment} style={{ color: 'var(--ok)', borderColor: 'var(--ok)' }}>添加特色设备</Button>

        {error && <Alert message={error} type="error" showIcon closable onClose={() => setError(null)} style={{ marginTop: 16 }} />}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--line-softer)' }}>
          <Button onClick={() => navigate(returnTo || '/departments')}>取消</Button>
          <Button type="primary" loading={loading} onClick={handleSubmit}>保存</Button>
        </div>
      </Card>

      <style>{`.df-img-wrap:hover .df-img-actions, .df-img-wrap:hover .df-img-btn { opacity: 1 !important; }`}</style>
    </PageContainer>
  );
};

export default DepartmentForm;
