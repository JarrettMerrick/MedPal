// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 文件详情抽屉：预览 + 元数据编辑 + 标签 + 版本历史 + 引用清单 + 回收站操作。
 *
 * [新增 2026-09-17] 需求：支持预览、下载、删除及批量处理；内置标准设计文件标记；
 * 同一文件保留历史版本（可回滚）；删除进回收站（可恢复 / 彻底删除）。
 *
 * 预览策略：图片与 PDF 走在线预览（以 blob 方式带令牌取回）；AI/PSD/CDR/EPS/ZIP
 * 浏览器无法内联渲染，提示下载后查看。图片/PDF 用 objectURL，避免静态直链绕过鉴权。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
// [修复 2026-09-17] 改用 App.useApp() 的实例方法：
// antd v5 的静态 message / Modal.confirm 无法消费 ConfigProvider 的 context，
// 控制台会提示「Static function can not consume context like dynamic theme」。
// 本文件无 <Modal> JSX 用法（仅静态 confirm），故 Modal 一并从导入中移除。
import {
  App, Button, Divider, Drawer, Empty, Image, Input, List, Popconfirm, Select,
  Space, Spin, Switch, Tag, Tooltip, Typography, Upload,
} from 'antd';
import {
  DeleteOutlined, DownloadOutlined, RollbackOutlined, StarFilled, UndoOutlined, UploadOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';

import {
  deleteDesignFile, getDesignFile, purgeDesignFile, restoreDesignFile,
  restoreDesignFileVersion, updateDesignFile, uploadDesignFileVersion,
} from '../../../api/designFiles';
import type { DesignFileDetail, FileCategoryItem, FileTag } from '../../../api/designFiles';
import {
  downloadDesignFile, fetchPreviewObjectUrl, fileExtLabel, formatFileSize,
} from '../../../utils/fileUtils';
import { formatDateTimeStandard } from '../../../utils/time';

const { Text } = Typography;

interface FileDetailDrawerProps {
  fileId: number | null;
  open: boolean;
  canEdit: boolean;
  canDelete: boolean;
  categories: FileCategoryItem[];
  tags: FileTag[];
  onClose: () => void;
  /** 元数据 / 版本 / 删除状态变化后通知父组件刷新列表与统计 */
  onChanged: () => void;
}

const FileDetailDrawer: React.FC<FileDetailDrawerProps> = ({
  fileId, open, canEdit, canDelete, categories, tags, onClose, onChanged,
}) => {
  // [修复 2026-09-17] 从 App context 获取 message / modal：可正确消费动态主题与国际化
  const { message, modal } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<DesignFileDetail | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);

  // 编辑态（保存时一次性提交）
  const [name, setName] = useState('');
  const [categoryId, setCategoryId] = useState<number | undefined>(undefined);
  const [isStandard, setIsStandard] = useState(false);
  const [remark, setRemark] = useState('');
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);

  // 版本上传
  const [versionNote, setVersionNote] = useState('');
  const [uploadingVersion, setUploadingVersion] = useState(false);

  const loadDetail = useCallback(async () => {
    if (!fileId) return;
    setLoading(true);
    try {
      const data = await getDesignFile(fileId);
      setDetail(data);
      setName(data.name);
      setCategoryId(data.category_id ?? undefined);
      setIsStandard(data.is_standard);
      setRemark(data.remark || '');
      setTagIds(data.tags.map((tag) => tag.id));
    } catch {
      message.error('加载文件详情失败');
    } finally {
      setLoading(false);
    }
  }, [fileId]);

  useEffect(() => {
    if (open && fileId) {
      loadDetail();
    } else if (!open) {
      setDetail(null);
      setPreviewUrl(null);
    }
  }, [open, fileId, loadDetail]);

  // 预览资源：图片/PDF 以 blob 取回，关闭或切换文件时释放 objectURL
  useEffect(() => {
    let createdUrl: string | null = null;
    setPreviewUrl(null);
    setPreviewFailed(false);
    if (!open || !detail || detail.preview_type === 'none') return undefined;
    fetchPreviewObjectUrl(detail.id)
      .then((url) => { createdUrl = url; setPreviewUrl(url); })
      .catch(() => setPreviewFailed(true));
    return () => {
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [open, detail]);

  // [调整 2026-09-17] 分类沿用标识分类（扁平结构），直接映射为选项；
  // 分类维护在「标识设置 → 标识分类」，此处仅用于给文件归类
  const categoryOptions = useMemo(
    () => categories.map((category) => ({
      value: category.id,
      label: category.is_active ? category.name : `${category.name}（已禁用）`,
    })),
    [categories],
  );

  const tagOptions = useMemo(
    () => tags.map((tag) => ({ value: tag.id, label: `${tag.group_name}：${tag.name}` })),
    [tags],
  );

  const handleSave = async () => {
    if (!detail) return;
    setSaving(true);
    try {
      const updated = await updateDesignFile(detail.id, {
        name,
        category_id: categoryId ?? null,
        is_standard: isStandard,
        remark,
        tag_ids: tagIds,
      });
      setDetail(updated);
      message.success('已保存');
      onChanged();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleVersionUpload = async (file: File) => {
    if (!detail) return false;
    setUploadingVersion(true);
    try {
      const updated = await uploadDesignFileVersion(detail.id, file, versionNote.trim() || undefined);
      setDetail(updated);
      setVersionNote('');
      message.success('新版本已上传；引用该文件的标识已自动指向新版本');
      onChanged();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '版本上传失败');
    } finally {
      setUploadingVersion(false);
    }
    return false;
  };

  const handleRollback = async (versionId: number) => {
    if (!detail) return;
    try {
      const updated = await restoreDesignFileVersion(detail.id, versionId);
      setDetail(updated);
      message.success('已回滚到该版本');
      onChanged();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '回滚失败');
    }
  };

  const handleDelete = async () => {
    if (!detail) return;
    try {
      await deleteDesignFile(detail.id);
      message.success('已移入回收站');
      onChanged();
      onClose();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除失败');
    }
  };

  const handleRestore = async () => {
    if (!detail) return;
    try {
      await restoreDesignFile(detail.id);
      message.success('已恢复');
      onChanged();
      onClose();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '恢复失败');
    }
  };

  const handlePurge = () => {
    if (!detail) return;
    modal.confirm({
      title: `彻底删除「${detail.name}」？`,
      content: '将同时删除该文件的所有历史版本与磁盘文件，且不可恢复。',
      okText: '彻底删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await purgeDesignFile(detail.id);
          message.success('已彻底删除');
          onChanged();
          onClose();
        } catch (error: any) {
          message.error(error?.response?.data?.detail || '彻底删除失败');
        }
      },
    });
  };

  const renderPreview = () => {
    if (!detail) return null;
    if (detail.preview_type === 'none') {
      return (
        <div className="file-preview file-preview--none">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span>
                {fileExtLabel(detail.file_ext)} 文件不支持在线预览，
                <br />
                请下载后使用专业软件查看
              </span>
            }
          />
          <Button icon={<DownloadOutlined />} onClick={() => downloadDesignFile(detail.id, detail.name)}>
            下载文件
          </Button>
        </div>
      );
    }
    if (previewFailed) {
      return <div className="file-preview file-preview--none"><Text type="danger">预览加载失败，请下载后查看</Text></div>;
    }
    if (!previewUrl) {
      return <div className="file-preview file-preview--loading"><Spin /></div>;
    }
    if (detail.preview_type === 'image') {
      return (
        <div className="file-preview">
          <Image src={previewUrl} alt={detail.name} style={{ maxHeight: 380, objectFit: 'contain' }} />
        </div>
      );
    }
    // PDF：浏览器内置查看器（blob URL 保持鉴权链）
    return (
      <div className="file-preview">
        <iframe src={previewUrl} title={detail.name} className="file-preview__pdf" />
      </div>
    );
  };

  return (
    <Drawer
      title={detail ? detail.name : '文件详情'}
      open={open}
      onClose={onClose}
      width={760}
      destroyOnHidden
      extra={
        detail && (
          <Space>
            <Tooltip title="下载文件">
              <Button
                icon={<DownloadOutlined />}
                onClick={() => downloadDesignFile(detail.id, detail.name)}
              >
                下载
              </Button>
            </Tooltip>
            {detail.is_deleted
              ? canDelete && (
                <>
                  <Button icon={<RollbackOutlined />} onClick={handleRestore}>恢复</Button>
                  <Popconfirm
                    title="彻底删除该文件？"
                    description="将删除全部历史版本与磁盘文件，不可恢复。"
                    okText="彻底删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={handlePurge}
                  >
                    <Button danger icon={<DeleteOutlined />}>彻底删除</Button>
                  </Popconfirm>
                </>
              )
              : canDelete && (
                <Popconfirm
                  title="移入回收站？"
                  description="被标识引用的文件无法删除，需先在标识中解除引用。"
                  okText="移入回收站"
                  cancelText="取消"
                  onConfirm={handleDelete}
                >
                  <Button danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              )}
          </Space>
        )
      }
    >
      {loading || !detail ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {renderPreview()}

          {/* 基本信息 */}
          <div className="file-detail__section">
            <div className="file-detail__row">
              <Text type="secondary">文件信息</Text>
              <Space size={8} wrap>
                <Tag>{fileExtLabel(detail.file_ext)}</Tag>
                <Tag>{formatFileSize(detail.file_size)}</Tag>
                <Tag>v{detail.current_version}</Tag>
                {detail.is_standard && <Tag color="gold" icon={<StarFilled />}>标准设计文件</Tag>}
                {detail.ref_count > 0 && <Tag color="blue">被 {detail.ref_count} 条标识引用</Tag>}
              </Space>
            </div>
            <div className="file-detail__row">
              <Text type="secondary">上传</Text>
              <span>
                {detail.uploader_name || detail.uploader_id || '未知'}
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  {detail.created_at ? formatDateTimeStandard(detail.created_at) : ''}
                </Text>
              </span>
            </div>
          </div>

          <Divider style={{ margin: '4px 0' }} />

          {/* 元数据编辑 */}
          <div className="file-detail__section">
            <div className="file-detail__field">
              <label>显示名</label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={!canEdit}
                maxLength={200}
                placeholder="文件在文件库中的名称"
              />
            </div>
            <div className="file-detail__field">
              <label>所属分类</label>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="未分类"
                style={{ width: '100%' }}
                value={categoryId}
                onChange={setCategoryId}
                options={categoryOptions}
                disabled={!canEdit}
              />
            </div>
            <div className="file-detail__field">
              <label>标签</label>
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="选择标签（按维度归集）"
                value={tagIds}
                onChange={setTagIds}
                options={tagOptions}
                disabled={!canEdit}
              />
            </div>
            <div className="file-detail__field">
              <label>备注</label>
              <Input.TextArea
                rows={2}
                value={remark}
                onChange={(e) => setRemark(e.target.value)}
                disabled={!canEdit}
                placeholder="选填，例如适用场景说明"
              />
            </div>
            <div className="file-detail__field file-detail__field--inline">
              <label>
                <StarFilled style={{ color: 'var(--warn)', marginRight: 6 }} />
                标准设计文件
              </label>
              <Switch
                checked={isStandard}
                onChange={setIsStandard}
                disabled={!canEdit}
                checkedChildren="是"
                unCheckedChildren="否"
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                标记后，标识编辑页可通过「从标准库选择」搜索并复用该文件
              </Text>
            </div>
            {canEdit && (
              <Button type="primary" loading={saving} onClick={handleSave}>保存修改</Button>
            )}
          </div>

          {/* 版本历史 */}
          <div className="file-detail__section">
            <div className="file-detail__row">
              <Text strong>版本历史（{detail.versions.length}）</Text>
              {canEdit && (
                <Space>
                  <Input
                    size="small"
                    placeholder="版本说明（可选）"
                    value={versionNote}
                    onChange={(e) => setVersionNote(e.target.value)}
                    style={{ width: 200 }}
                    maxLength={200}
                  />
                  <Upload
                    showUploadList={false}
                    accept=".jpg,.jpeg,.png,.webp,.ai,.pdf,.psd,.cdr,.eps,.zip"
                    beforeUpload={(file) => { handleVersionUpload(file as File); return false; }}
                  >
                    <Button size="small" icon={<UploadOutlined />} loading={uploadingVersion}>
                      上传新版本
                    </Button>
                  </Upload>
                </Space>
              )}
            </div>
            <List
              size="small"
              dataSource={detail.versions}
              renderItem={(version) => (
                <List.Item
                  actions={canEdit && version.version !== detail.current_version ? [
                    <Popconfirm
                      key="rollback"
                      title={`回滚到 v${version.version}？`}
                      description="回滚后引用该文件的标识将指向该版本文件。"
                      okText="确认回滚"
                      cancelText="取消"
                      onConfirm={() => handleRollback(version.id)}
                    >
                      <Button type="link" size="small" icon={<UndoOutlined />}>回滚</Button>
                    </Popconfirm>,
                  ] : undefined}
                >
                  <Space size={8} wrap>
                    <Tag color={version.version === detail.current_version ? 'green' : 'default'}>
                      v{version.version}
                      {version.version === detail.current_version ? '（当前）' : ''}
                    </Tag>
                    <span>{version.note || '未填写说明'}</span>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {version.uploaded_by_name || version.uploaded_by || '未知'}
                      {version.created_at ? ` · ${formatDateTimeStandard(version.created_at)}` : ''}
                    </Text>
                  </Space>
                </List.Item>
              )}
            />
          </div>

          {/* 引用清单（引用共享：哪些标识在用这份文件） */}
          <div className="file-detail__section">
            <Text strong>引用该文件的标识（{detail.references.length}）</Text>
            {detail.references.length === 0 ? (
              <Text type="secondary">暂无标识引用；标记为标准设计文件后可在标识编辑页复用</Text>
            ) : (
              <List
                size="small"
                dataSource={detail.references}
                renderItem={(ref) => (
                  <List.Item>
                    <Space size={8}>
                      <Link to={`/signages/${ref.signage_id}`}>{ref.code || `#${ref.signage_id}`}</Link>
                      <span>{ref.name || '-'}</span>
                    </Space>
                  </List.Item>
                )}
              />
            )}
          </div>
        </Space>
      )}
    </Drawer>
  );
};

export default FileDetailDrawer;
