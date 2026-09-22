// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 标识维修操作（发起维修 / 完成维修）公共按钮 + 弹窗 + 提交逻辑。
 *
 * [新增 2026-09-17] 需求：「维修记录」页与「标识预警」页的操作按钮，样式与行为必须一致。
 * 原先整套弹窗与提交流程内联在「标识预警」页，若维修记录页再抄一份，
 * 两处会随迭代逐渐走形（按钮文案 / 图标 / 必填校验 / 照片处理 / 提示语）。
 * 因此统一收敛到本模块，两个页面共用同一份实现：
 *
 *   const { openRepair, openComplete, modals } = useSignageRepairActions({ onCompleted: reload });
 *   // 列表操作列：
 *   <SignageCompleteButton onClick={() => openComplete({ repair_id: r.id, signage_id: r.signage_id, name, code })} />
 *   // 页面底部渲染弹窗：
 *   {modals}
 *
 * 行为（与原「标识预警」页完全一致）：
 * - 发起维修：选择维修方（供应商维修 / 工程部维修）；供应商维修必选供应商，OA 单号可选；
 * - 完成维修：可选上传维修完成照片（客户端压缩后先上传，提交时带上路径），
 *   上传后由后端同步替换该标识的安装现场照片；
 * - 供应商下拉为避免每个使用方页面常驻请求，改为首次打开弹窗时按需加载。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import { App, Button, Input, Modal, Radio, Select, Space, Typography } from 'antd';
import { CameraOutlined, CheckCircleOutlined, PictureOutlined, ToolOutlined } from '@ant-design/icons';

import { completeSignageRepair, startSignageRepair, uploadRepairPhoto } from '../api/signage';
import { getActiveSuppliers } from '../api/signage-settings';
import type { Supplier } from '../api/signage-settings';
import { compressImageFile } from '../utils/imageUtils';

const { Text } = Typography;

/** 维修操作目标：发起维修用 signage_id，完成维修用 repair_id */
export interface SignageRepairTarget {
  /** 标识 ID（发起维修提交使用） */
  signage_id: number;
  /** 维修记录 ID（完成维修提交使用） */
  repair_id?: number;
  /** 标识名称 / 编码（仅用于弹窗标题展示） */
  name?: string;
  code?: string;
}

/** 「标识维修」（发起维修）按钮：样式与「标识预警」页完全一致 */
export const SignageRepairButton: React.FC<{ onClick: () => void; disabled?: boolean }> = ({
  onClick, disabled,
}) => (
  <Button size="small" type="primary" icon={<ToolOutlined />} onClick={onClick} disabled={disabled}>
    标识维修
  </Button>
);

/** 「完成维修」按钮：样式与「标识预警」页完全一致 */
export const SignageCompleteButton: React.FC<{ onClick: () => void; disabled?: boolean }> = ({
  onClick, disabled,
}) => (
  <Button size="small" icon={<CheckCircleOutlined />} onClick={onClick} disabled={disabled}>
    完成维修
  </Button>
);

interface UseSignageRepairActionsOptions {
  /** 发起维修成功后回调（刷新列表 / 预警红点等） */
  onStarted?: () => void;
  /** 完成维修成功后回调（刷新列表 / 预警红点等） */
  onCompleted?: () => void;
}

export function useSignageRepairActions(options?: UseSignageRepairActionsOptions) {
  // [修复 2026-09-17] 从 App context 获取 message 实例（自定义 Hook 内调用同样有效）
  const { message } = App.useApp();
  // 回调存 ref：避免使用方传入内联箭头函数导致每次渲染重建闭包
  const onStartedRef = useRef(options?.onStarted);
  const onCompletedRef = useRef(options?.onCompleted);
  useEffect(() => { onStartedRef.current = options?.onStarted; }, [options?.onStarted]);
  useEffect(() => { onCompletedRef.current = options?.onCompleted; }, [options?.onCompleted]);

  // ===== 发起维修（状态异常 → 维修处理中）=====
  const [repairTarget, setRepairTarget] = useState<SignageRepairTarget | null>(null);
  const [repairParty, setRepairParty] = useState<'vendor' | 'engineering'>('engineering');
  const [oaNumber, setOaNumber] = useState('');
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [repairSubmitting, setRepairSubmitting] = useState(false);

  // ===== 完成维修（维修处理中 → 正常，可选上传照片）=====
  const [completeTarget, setCompleteTarget] = useState<SignageRepairTarget | null>(null);
  const [repairPhotoPreview, setRepairPhotoPreview] = useState<string | null>(null);
  const [repairPhotoPath, setRepairPhotoPath] = useState<string | undefined>(undefined);
  const [repairPhotoUploading, setRepairPhotoUploading] = useState(false);
  const [completeSubmitting, setCompleteSubmitting] = useState(false);
  const repairPhotoInputRef = useRef<HTMLInputElement | null>(null);
  // [新增 2026-09-19] 独立的后置摄像头 input：带 capture 属性，移动端直接唤起相机拍照
  const cameraInputRef = useRef<HTMLInputElement | null>(null);

  // 供应商列表按需加载：首次打开「发起维修」弹窗时拉取一次
  const suppliersLoadedRef = useRef(false);
  const ensureSuppliers = useCallback(() => {
    if (suppliersLoadedRef.current) return;
    getActiveSuppliers()
      .then((list) => { setSuppliers(list); suppliersLoadedRef.current = true; })
      .catch(() => setSuppliers([]));
  }, []);

  // 预览 URL 生命周期：卸载时释放
  useEffect(() => () => {
    if (repairPhotoPreview) URL.revokeObjectURL(repairPhotoPreview);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ----- 发起维修 -----
  const openRepair = useCallback((target: SignageRepairTarget) => {
    ensureSuppliers();
    setRepairTarget(target);
    setRepairParty('engineering');
    setOaNumber('');
    setSupplierId(undefined);
  }, [ensureSuppliers]);

  const handleStartRepair = async () => {
    if (!repairTarget) return;
    if (repairParty === 'vendor' && !supplierId) {
      message.warning('选择供应商维修时必须选择供应商');
      return;
    }
    setRepairSubmitting(true);
    try {
      await startSignageRepair({
        signage_id: repairTarget.signage_id,
        repair_party: repairParty,
        oa_number: repairParty === 'vendor' && oaNumber.trim() ? oaNumber.trim() : undefined,
        supplier_id: repairParty === 'vendor' ? supplierId : undefined,
      });
      message.success('已发起维修，状态变更为「维修处理中」');
      setRepairTarget(null);
      onStartedRef.current?.();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '发起维修失败');
    } finally {
      setRepairSubmitting(false);
    }
  };

  // ----- 完成维修 -----
  const openComplete = useCallback((target: SignageRepairTarget) => {
    setCompleteTarget(target);
    setRepairPhotoPreview(null);
    setRepairPhotoPath(undefined);
  }, []);

  const closeCompleteModal = useCallback(() => {
    if (repairPhotoPreview) URL.revokeObjectURL(repairPhotoPreview);
    setCompleteTarget(null);
    setRepairPhotoPreview(null);
    setRepairPhotoPath(undefined);
  }, [repairPhotoPreview]);

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
    // 完成维修必须携带维修记录 ID（由调用方在 openComplete 时传入）
    if (!completeTarget.repair_id) {
      message.error('缺少维修记录 ID，无法完成维修');
      return;
    }
    setCompleteSubmitting(true);
    try {
      await completeSignageRepair(completeTarget.repair_id, repairPhotoPath);
      message.success('维修已完成，状态变更为「正常」');
      closeCompleteModal();
      onCompletedRef.current?.();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '完成维修失败');
    } finally {
      setCompleteSubmitting(false);
    }
  };

  const modals = (
    <>
      {/* 发起维修弹窗：选择维修方；供应商维修需选供应商（OA 单号可选） */}
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
            <Text type="secondary">工程部维修可直接确认，状态将变更为「维修处理中」。</Text>
          )}
        </Space>
      </Modal>

      {/* 完成维修弹窗：可选上传维修完成照片（上传后替换标识安装现场照片） */}
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
            确认后状态自动变更为「正常」；可选择性上传维修完成照片，上传后将替换标识详情页的安装现场照片。
          </Text>
          {repairPhotoPreview ? (
            <>
              <img
                src={repairPhotoPreview}
                alt="维修完成照片预览"
                /* [改造 2026-09-19] 预览底改引用变量：图片衬底在深色下不再刺眼 */
                style={{ width: '100%', maxHeight: 260, objectFit: 'contain', borderRadius: 'var(--radius-control)', background: 'var(--neu-bg)' }}
              />
              <Space>
                <Button icon={<PictureOutlined />} disabled={repairPhotoUploading} onClick={() => repairPhotoInputRef.current?.click()}>
                  重新选择
                </Button>
                <Button type="text" danger onClick={clearRepairPhoto}>移除照片</Button>
              </Space>
            </>
          ) : (
            /* [调整 2026-09-19] 由单个「上传照片」按钮拆为「拍照 / 从文件选择」两个入口：
               原先只有 type="file" 的文件选择，在手机上虽然部分浏览器会附带"拍照"选项，
               但并不可靠（iOS Safari 需长按、部分安卓浏览器无该入口），
               现场维修时最常用的正是**随手拍一张**，因此补一个带
               capture="environment" 的独立 input —— 它会直接唤起后置摄像头。 */
            <Space wrap>
              <Button icon={<CameraOutlined />} loading={repairPhotoUploading} onClick={() => cameraInputRef.current?.click()}>
                拍照
              </Button>
              <Button icon={<PictureOutlined />} loading={repairPhotoUploading} onClick={() => repairPhotoInputRef.current?.click()}>
                从文件选择
              </Button>
            </Space>
          )}
          <input
            ref={repairPhotoInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={handleRepairPhotoSelected}
          />
          {/* capture="environment" → 移动端直接开后置摄像头；桌面端会退化为普通文件选择 */}
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: 'none' }}
            onChange={handleRepairPhotoSelected}
          />
        </Space>
      </Modal>
    </>
  );

  return {
    openRepair,
    openComplete,
    /** 需在页面中渲染的弹窗节点 */
    modals,
    /** 是否有弹窗正在提交（供页面按需禁用其他操作） */
    submitting: repairSubmitting || completeSubmitting,
  };
}

export default useSignageRepairActions;
