// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file in the project root for details.

/**
 * 文件管理页：集中管理所有已上传的设计文件。
 *
 * [新增 2026-09-17] 需求（参考成熟 DAM 方案的功能结构）：
 *   1) 搜索：文件名 / 标签 / 上传时间 / 引用标识（关键词一并匹配引用该文件的标识编码与名称）
 *   2) 分类：沿用「标识设置 → 标识分类」（左栏只读筛选，**无增删改入口**）
 *   3) 打标签：按维度（项目 / 类型 / 状态…）多值标签，支持批量打标与移除
 *   4) 文件操作：预览 / 下载 / 删除 / 批量处理（移动分类、打标、标记标准、删除、恢复、彻底删除）
 *   5) 标准设计文件：标记后可在标识编辑页「从标准库选择」中搜索复用（引用共享）
 *
 * 交互骨架参考 ResourceSpace（左侧集合树 + 中部资源列表 + 右侧详情）与 Eagle（标签 + 文件夹双体系）。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）。
// Modal 仍用于上传弹窗的 <Modal> JSX，保留导入。
import {
  App, Button, Card, Col, DatePicker, Input, Modal, Popconfirm, Row, Select, Space, Table,
  Tag, Tooltip, Typography, Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd';
import {
  DeleteOutlined, DownloadOutlined, InboxOutlined, RollbackOutlined, SearchOutlined,
  StarFilled, StarOutlined, TagsOutlined, UploadOutlined,
} from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';

import { useAuth } from '../../contexts/AuthContext';
import {
  hasPermission, PERM_FILE_DELETE, PERM_FILE_EDIT, PERM_FILE_UPLOAD, PERM_FILE_VIEW,
  PERM_SIGNAGE_CATEGORY,
} from '../../utils/permissions';
import {
  batchDeleteFiles, batchPurgeFiles, batchRestoreFiles, batchSetCategory, batchSetStandard,
  batchSetTags, downloadFilesZip, getDesignFileSummary, listDesignFiles, listFileCategories,
  listFileTags, uploadDesignFiles,
} from '../../api/designFiles';
import type {
  DesignFileItem, DesignFileListParams, DesignFileSummary, FileCategoryItem, FileTag,
} from '../../api/designFiles';
import { downloadDesignFile, fileExtLabel, formatFileSize } from '../../utils/fileUtils';
import { formatDateTimeStandard } from '../../utils/time';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import CategoryTree, { selectionKey } from './components/CategoryTree';
import type { CategorySelection } from './components/CategoryTree';
import TagManagerModal from './components/TagManagerModal';
import FileDetailDrawer from './components/FileDetailDrawer';

const { Text } = Typography;

/**
 * [新增 2026-09-17] 从 blob 类型的错误响应中取出后端 detail。
 * axios 设置 responseType: 'blob' 时，错误响应体同样是 Blob，
 * 直接读 error.response.data.detail 会得到 undefined，需先读出文本再解析 JSON。
 */
async function readBlobErrorDetail(error: any): Promise<string> {
  const data = error?.response?.data;
  if (!(data instanceof Blob)) {
    return typeof data?.detail === 'string' ? data.detail : '';
  }
  try {
    const parsed = JSON.parse(await data.text());
    if (typeof parsed?.detail === 'string') return parsed.detail;
    if (Array.isArray(parsed?.detail)) {
      return parsed.detail.map((item: any) => item?.msg).filter(Boolean).join('；');
    }
  } catch {
    // 非 JSON（如网关返回的 HTML），忽略
  }
  return '';
}
const { RangePicker } = DatePicker;

const DesignFileManager: React.FC = () => {
  const { user } = useAuth();
  const canView = hasPermission(user, PERM_FILE_VIEW);
  const canUpload = hasPermission(user, PERM_FILE_UPLOAD);
  const canEdit = hasPermission(user, PERM_FILE_EDIT);
  const canDelete = hasPermission(user, PERM_FILE_DELETE);
  // [新增 2026-09-17] 分类沿用「标识设置 → 标识分类」：本页只读，
  // 仅对拥有标识分类维护权限的账号展示「维护」跳转入口
  const canManageCategory = hasPermission(user, PERM_SIGNAGE_CATEGORY);
  // [修复 2026-09-17] 从 App context 获取 message / modal 实例：
  // 静态方法无法消费 ConfigProvider 的动态主题（控制台会给出提示）
  const { message, modal } = App.useApp();

  // 检索条件
  const [selection, setSelection] = useState<CategorySelection>({ kind: 'all' });
  const [keyword, setKeyword] = useState('');
  const [tagFilter, setTagFilter] = useState<number[]>([]);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // 数据
  const [items, setItems] = useState<DesignFileItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [categories, setCategories] = useState<FileCategoryItem[]>([]);
  const [tags, setTags] = useState<FileTag[]>([]);
  const [summary, setSummary] = useState<DesignFileSummary | null>(null);

  // 选中与弹窗
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  // [新增 2026-09-17] 批量打包下载进行中（打包在服务端完成，前端仅需防重复点击）
  const [zipping, setZipping] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [detailFileId, setDetailFileId] = useState<number | null>(null);

  // 上传表单
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([]);
  const [uploadCategoryId, setUploadCategoryId] = useState<number | undefined>(undefined);
  const [uploadStandard, setUploadStandard] = useState(false);
  const [uploading, setUploading] = useState(false);

  const isTrash = selection.kind === 'trash';

  const buildParams = useCallback((): DesignFileListParams => {
    const params: DesignFileListParams = {
      page,
      page_size: pageSize,
      keyword: keyword.trim() || undefined,
      tag_ids: tagFilter.length ? tagFilter : undefined,
      only_deleted: isTrash,
    };
    if (selection.kind === 'category') params.category_id = selection.id;
    if (selection.kind === 'uncategorized') params.uncategorized = true;
    if (selection.kind === 'standard') params.is_standard = true;
    if (range?.[0]) params.start_date = range[0].format('YYYY-MM-DD');
    if (range?.[1]) params.end_date = range[1].format('YYYY-MM-DD');
    return params;
  }, [page, pageSize, keyword, tagFilter, selection, range, isTrash]);

  const fetchFiles = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listDesignFiles(buildParams());
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error('获取文件列表失败');
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  const fetchTaxonomy = useCallback(async () => {
    try {
      const [categoryRes, tagRes, summaryRes] = await Promise.all([
        listFileCategories(), listFileTags(), getDesignFileSummary(),
      ]);
      setCategories(categoryRes.items);
      setTags(tagRes.items);
      setSummary(summaryRes);
    } catch {
      // 辅助信息：失败静默（列表仍可用）
    }
  }, []);

  useEffect(() => { if (canView) fetchFiles(); }, [canView, fetchFiles]);
  useEffect(() => { if (canView) fetchTaxonomy(); }, [canView, fetchTaxonomy]);

  // 分类切换时回到第 1 页并清空选中
  useEffect(() => {
    setPage(1);
    setSelectedKeys([]);
  }, [selection, keyword, tagFilter, range]);

  const refreshAll = () => {
    fetchFiles();
    fetchTaxonomy();
  };

  // [调整 2026-09-17] 分类为扁平结构（标识分类无层级），无需再递归展开
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

  const currentCategoryName = useMemo(() => {
    if (selection.kind !== 'category') return null;
    const found = categoryOptions.find((option) => option.value === selection.id);
    return found ? found.label.trim() : null;
  }, [selection, categoryOptions]);

  // ==================== 批量操作 ====================

  const ids = selectedKeys.map((key) => Number(key));

  const handleBatchCategory = async (categoryId: number) => {
    if (!ids.length) return;
    try {
      const result = await batchSetCategory(ids, categoryId);
      message.success(`已将 ${result.updated} 个文件移动到新分类`);
      setSelectedKeys([]);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量移动失败');
    }
  };

  const handleBatchTags = async (tagIds: number[]) => {
    if (!ids.length || !tagIds.length) return;
    try {
      const result = await batchSetTags(ids, tagIds, []);
      message.success(`已为 ${ids.length} 个文件新增 ${result.added} 个标签关联`);
      setSelectedKeys([]);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量打标签失败');
    }
  };

  const handleBatchStandard = async (isStandard: boolean) => {
    if (!ids.length) return;
    try {
      const result = await batchSetStandard(ids, isStandard);
      message.success(`已${isStandard ? '标记' : '取消标记'} ${result.updated} 个文件`);
      setSelectedKeys([]);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '操作失败');
    }
  };

  const handleBatchDelete = async () => {
    if (!ids.length) return;
    try {
      const result = await batchDeleteFiles(ids);
      if (result.blocked.length) {
        message.warning(
          `${result.deleted} 个文件已移入回收站；${result.blocked.length} 个文件被标识引用，未删除`,
        );
      } else {
        message.success(`已将 ${result.deleted} 个文件移入回收站`);
      }
      setSelectedKeys([]);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量删除失败');
    }
  };

  const handleBatchRestore = async () => {
    if (!ids.length) return;
    try {
      const result = await batchRestoreFiles(ids);
      message.success(`已恢复 ${result.restored} 个文件`);
      setSelectedKeys([]);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量恢复失败');
    }
  };

  const handleBatchPurge = async () => {
    if (!ids.length) return;
    try {
      const result = await batchPurgeFiles(ids);
      if (result.blocked.length) {
        message.warning(
          `${result.purged} 个文件已彻底删除；${result.blocked.length} 个被标识引用，未删除`,
        );
      } else {
        message.success(`已彻底删除 ${result.purged} 个文件`);
      }
      setSelectedKeys([]);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量彻底删除失败');
    }
  };

  /**
   * [新增 2026-09-17] 批量打包下载（需求方案 A）：
   * 勾选文件 → 服务端按分类目录打包 zip → 浏览器下载。
   * 目录用标识分类名（未分类归入「未分类」），文件名用文件管理中的「使用名」。
   */
  const handleBatchDownload = async () => {
    if (!ids.length) return;
    setZipping(true);
    try {
      const result = await downloadFilesZip(ids);
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = result.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      if (result.skipped > 0) {
        message.warning(
          `已打包 ${result.packed} 个文件；${result.skipped} 个文件在服务器上缺失，已跳过`,
        );
      } else {
        message.success(`已打包 ${result.packed} 个文件，开始下载`);
      }
    } catch (error: any) {
      message.error((await readBlobErrorDetail(error)) || '打包下载失败');
    } finally {
      setZipping(false);
    }
  };

  // ==================== 上传 ====================

  const handleUpload = async () => {
    const files = uploadFiles
      .map((item) => item.originFileObj as File | undefined)
      .filter((file): file is File => Boolean(file));
    if (!files.length) {
      message.warning('请先选择要上传的文件');
      return;
    }
    setUploading(true);
    try {
      const result = await uploadDesignFiles(files, {
        category_id: uploadCategoryId,
        is_standard: uploadStandard,
      });
      if (result.errors.length) {
        modal.warning({
          title: `上传完成：成功 ${result.total} 个，失败 ${result.errors.length} 个`,
          content: (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {result.errors.map((err, index) => (
                <li key={index}>{err.filename || '未知文件'}：{err.detail}</li>
              ))}
            </ul>
          ),
        });
      } else {
        message.success(`已上传 ${result.total} 个文件`);
      }
      setUploadOpen(false);
      setUploadFiles([]);
      setUploadStandard(false);
      setUploadCategoryId(undefined);
      refreshAll();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  // ==================== 表格 ====================

  const columns: ColumnsType<DesignFileItem> = [
    {
      title: '预览', key: 'thumbnail', width: 92, align: 'center',
      render: (_, record) => {
        const thumb = record.thumbnail_path;
        if (record.preview_type === 'image' && thumb) {
          return (
            <div className="file-thumb">
              <img src={`/uploads/${thumb}`} alt={record.name} loading="lazy" />
            </div>
          );
        }
        return (
          <div className="file-thumb file-thumb--ext">
            <span>{fileExtLabel(record.file_ext)}</span>
          </div>
        );
      },
    },
    {
      // [调整 2026-09-19] 去掉固定宽度 260，改为自适应 + 允许换行。
      // 本表原 7 列全部定宽（合计 1102px），无列可伸缩 → 窄屏必然横向滚动。
      // 「文件名称」是全表最长内容（文件名 + 标准/引用标签 + 扩展名），
      // 由它吸收剩余空间：宽屏展开、窄屏折行，文件名不再被硬挤。
      title: '文件名称', key: 'name',
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 180 } as React.CSSProperties,
      }),
      render: (_, record) => (
        <div className="file-name-cell">
          <a onClick={() => setDetailFileId(record.id)}>{record.name}</a>
          <Space size={4} style={{ marginTop: 2 }} wrap>
            {record.is_standard && (
              <Tag color="gold" icon={<StarFilled />} style={{ marginInlineEnd: 0 }}>标准</Tag>
            )}
            {record.ref_count > 0 && (
              <Tag color="blue" style={{ marginInlineEnd: 0 }}>引用 {record.ref_count}</Tag>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>{fileExtLabel(record.file_ext)}</Text>
          </Space>
        </div>
      ),
    },
    {
      title: '分类', key: 'category', width: 130,
      render: (_, record) => record.category_name
        ? <Tag>{record.category_name}</Tag>
        : <Text type="secondary">未分类</Text>,
    },
    {
      title: '标签', key: 'tags', width: 200,
      render: (_, record) => record.tags.length
        ? (
          <Space size={4} wrap>
            {record.tags.map((tag) => (
              <Tag key={tag.id} color={tag.color || 'default'} style={{ marginInlineEnd: 0 }}>
                {tag.name}
              </Tag>
            ))}
          </Space>
        )
        : <Text type="secondary">-</Text>,
    },
    {
      title: '大小', dataIndex: 'file_size', key: 'size', width: 90,
      render: (value: number | null) => formatFileSize(value),
    },
    {
      title: '上传', key: 'uploader', width: 170,
      render: (_, record) => (
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>
          <div>{record.uploader_name || record.uploader_id || '未知'}</div>
          <div style={{ color: 'var(--text-2)' }}>
            {record.created_at ? formatDateTimeStandard(record.created_at) : '-'}
          </div>
        </div>
      ),
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_, record) => (
        <Space size={2}>
          <Button type="link" size="small" onClick={() => setDetailFileId(record.id)}>详情</Button>
          <Tooltip title="下载">
            <Button
              type="link" size="small" icon={<DownloadOutlined />}
              onClick={() => downloadDesignFile(record.id, record.name)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  if (!canView) {
    return (
      <PageContainer>
        <PageHeader title="文件管理" description="集中管理设计文件" />
        <Card><Text type="secondary">你没有文件库的查看权限（file.view），请联系管理员分配。</Text></Card>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="文件管理"
        description="集中管理所有已上传的设计文件：检索、标签、版本与标准设计文件复用；分类沿用「标识设置 → 标识分类」"
        extra={
          <Space>
            <Button icon={<TagsOutlined />} onClick={() => setTagManagerOpen(true)}>
              标签管理
            </Button>
            {canUpload && (
              <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
                上传文件
              </Button>
            )}
          </Space>
        }
      />

      <Row gutter={16} align="stretch">
        {/* 左栏：分类树 */}
        <Col xs={24} lg={6} xl={5}>
          <Card size="small" className="file-category-card">
            {/* [调整 2026-09-17] 分类栏只读：不再传入分类增删改能力 */}
            <CategoryTree
              categories={categories}
              selection={selection}
              onSelect={setSelection}
              summary={summary}
              canManageCategory={canManageCategory}
            />
          </Card>
        </Col>

        {/* 右栏：检索 + 列表 */}
        <Col xs={24} lg={18} xl={19}>
          <Card size="small">
            <Space wrap style={{ marginBottom: 12 }}>
              <Input
                allowClear
                placeholder="搜索文件名 / 备注 / 引用该文件的标识"
                prefix={<SearchOutlined />}
                style={{ width: 260 }}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={() => fetchFiles()}
              />
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="按标签筛选（多选为「同时包含」）"
                style={{ minWidth: 220, maxWidth: 360 }}
                value={tagFilter}
                onChange={setTagFilter}
                options={tagOptions}
              />
              <RangePicker
                value={range}
                onChange={(value) => setRange(value as [Dayjs, Dayjs] | null)}
                placeholder={['上传起', '上传止']}
              />
              <Button type="primary" icon={<SearchOutlined />} onClick={() => fetchFiles()}>查询</Button>
              <Button
                onClick={() => { setKeyword(''); setTagFilter([]); setRange(null); setSelection({ kind: 'all' }); }}
              >
                重置
              </Button>
            </Space>

            <div className="file-list__meta">
              <Text type="secondary">
                {selection.kind === 'trash' && '回收站：'}
                {selection.kind === 'standard' && '标准设计文件：'}
                {selection.kind === 'uncategorized' && '未分类：'}
                {currentCategoryName ? `${currentCategoryName}：` : ''}
                共 {total} 个文件
                {summary ? ` · 占用 ${formatFileSize(summary.total_size)}` : ''}
              </Text>
            </div>

            {/* 批量工具栏：有选中时出现 */}
            {selectedKeys.length > 0 && (
              <div className="file-batch-bar">
                <Text strong>已选 {selectedKeys.length} 项</Text>
                {isTrash ? (
                  <>
                    <Popconfirm
                      title={`恢复选中的 ${selectedKeys.length} 个文件？`}
                      okText="确认恢复" cancelText="取消" onConfirm={handleBatchRestore}
                    >
                      <Button size="small" icon={<RollbackOutlined />} disabled={!canDelete}>恢复</Button>
                    </Popconfirm>
                    <Popconfirm
                      title={`彻底删除选中的 ${selectedKeys.length} 个文件？`}
                      description="将删除全部历史版本与磁盘文件，不可恢复。"
                      okText="彻底删除" cancelText="取消" okButtonProps={{ danger: true }}
                      onConfirm={handleBatchPurge}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />} disabled={!canDelete}>彻底删除</Button>
                    </Popconfirm>
                  </>
                ) : (
                  <>
                    <Select
                      placeholder="移动到分类"
                      style={{ width: 170 }}
                      disabled={!canEdit}
                      options={categoryOptions}
                      value={undefined}
                      onChange={handleBatchCategory}
                    />
                    <Select
                      mode="multiple"
                      placeholder="批量打标签"
                      style={{ minWidth: 190, maxWidth: 280 }}
                      disabled={!canEdit}
                      options={tagOptions}
                      value={[]}
                      onChange={handleBatchTags}
                    />
                    <Button
                      size="small" icon={<StarOutlined />} disabled={!canEdit}
                      onClick={() => handleBatchStandard(true)}
                    >
                      标记标准
                    </Button>
                    <Button
                      size="small" disabled={!canEdit}
                      onClick={() => handleBatchStandard(false)}
                    >
                      取消标准
                    </Button>
                    {/* [新增 2026-09-17] 批量打包下载：按分类目录打包 zip（文件名用使用名） */}
                    <Button
                      size="small" icon={<DownloadOutlined />}
                      loading={zipping}
                      onClick={handleBatchDownload}
                    >
                      批量下载
                    </Button>
                    <Popconfirm
                      title={`将选中的 ${selectedKeys.length} 个文件移入回收站？`}
                      description="被标识引用的文件会被自动跳过。"
                      okText="移入回收站" cancelText="取消"
                      onConfirm={handleBatchDelete}
                    >
                      <Button size="small" danger icon={<DeleteOutlined />} disabled={!canDelete}>删除</Button>
                    </Popconfirm>
                  </>
                )}
                <Button size="small" type="text" onClick={() => setSelectedKeys([])}>取消选择</Button>
              </div>
            )}

            <Table<DesignFileItem>
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={items}
              columns={columns}
              rowSelection={{
                selectedRowKeys: selectedKeys,
                onChange: setSelectedKeys,
              }}
              onRow={(record) => ({
                onDoubleClick: () => setDetailFileId(record.id),
              })}
              pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: true,
                showTotal: (value) => `共 ${value} 条`,
                onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
              }}
            />
          </Card>
        </Col>
      </Row>

      {/* 上传弹窗 */}
      <Modal
        title="上传文件到文件库"
        open={uploadOpen}
        onOk={handleUpload}
        onCancel={() => setUploadOpen(false)}
        confirmLoading={uploading}
        okText="开始上传"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Upload.Dragger
            multiple
            fileList={uploadFiles}
            beforeUpload={() => false}
            onChange={({ fileList }) => setUploadFiles(fileList)}
            accept=".jpg,.jpeg,.png,.webp,.ai,.pdf,.psd,.cdr,.eps,.zip"
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽文件到此处（支持多选）</p>
            <p className="ant-upload-hint">
              支持 JPG / PNG / WebP / AI / PDF / PSD / CDR / EPS / ZIP，单文件不超过 20MB
            </p>
          </Upload.Dragger>

          <div>
            <Text strong style={{ display: 'block', marginBottom: 6 }}>所属分类</Text>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="未分类（可稍后整理）"
              style={{ width: '100%' }}
              value={uploadCategoryId}
              onChange={setUploadCategoryId}
              options={categoryOptions}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Text strong>标记为标准设计文件</Text>
            <Select
              style={{ width: 120 }}
              value={uploadStandard ? 'yes' : 'no'}
              onChange={(value) => setUploadStandard(value === 'yes')}
              options={[
                { value: 'no', label: '否' },
                { value: 'yes', label: '是' },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              标记后可在标识编辑页搜索复用（引用共享，不复制文件）
            </Text>
          </div>
        </Space>
      </Modal>

      {/* 标签管理 */}
      <TagManagerModal
        open={tagManagerOpen}
        tags={tags}
        canEdit={canEdit}
        onClose={() => setTagManagerOpen(false)}
        onChanged={() => { fetchTaxonomy(); fetchFiles(); }}
      />

      {/* 文件详情 */}
      <FileDetailDrawer
        fileId={detailFileId}
        open={detailFileId !== null}
        canEdit={canEdit}
        canDelete={canDelete}
        categories={categories}
        tags={tags}
        onClose={() => setDetailFileId(null)}
        onChanged={refreshAll}
      />
    </PageContainer>
  );
};

export default DesignFileManager;
