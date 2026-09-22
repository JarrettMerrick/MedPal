// [重构 2026-09-07] 标识导入导出页：
// ① 数据导出：按院区/楼栋/分类/状态/关键词筛选，导出 Excel / CSV（列与导入模板一致）；
// ② 附件批量导出：两步式——先生成后台打包任务（单卷≤500MB 自动分卷），再按分卷下载；压缩包保留 24 小时；
// ③ 数据导入：下载 xlsx 模板 → 上传模板文件批量导入，展示成功/跳过/逐行错误明细。
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { downloadBlob as downloadBlobCore } from '../../utils/fileUtils';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import {
  App, Card, Button, Select, Input, Space, Checkbox, Upload, Alert, Divider, Typography, Spin,
  // [新增 2026-09-22] Popconfirm：删除导出任务前的二次确认
  Popconfirm,
} from 'antd';
import {
  DownloadOutlined, FileExcelOutlined, FileTextOutlined, FolderOpenOutlined,
  UploadOutlined, FileAddOutlined,
  // [新增 2026-09-22] 删除按钮图标
  DeleteOutlined,
} from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { campusApi } from '../../api/campus';
import { getActiveSignageCategories } from '../../api/signage-settings';
import { SIGNAGE_STATUS_OPTIONS } from '../../constants/signageStatus';
// [改进 2026-09-21 / Q-12] 统一错误文案提取（detail 优先、按状态码回落、message 兜底）
import api, { getErrorMessage } from '../../api/client';
import { formatDateTimeStandard } from '../../utils/time';

const { Text } = Typography;

/**
 * 带鉴权下载文件 Blob（导出接口返回二进制流）
 * [修复 2026-09-08] 改走 axios 客户端：原先裸 fetch 读取了不存在的 localStorage 'token' 键
 * （实际键名为 access_token），导致 Authorization: Bearer null 恒定 401；
 * 且裸 fetch 不经过拦截器，令牌过期时无法静默刷新。现走 api 实例自动携带令牌并支持 401 静默刷新重试。
 */
async function downloadBlob(url: string, filename: string): Promise<void> {
  let response;
  try {
    // axios 实例 baseURL 为 /api，传入的 url 已带 /api 前缀，需去掉避免拼接成 /api/api
    response = await api.get(url.replace(/^\/api/, ''), { responseType: 'blob' });
  } catch (e: any) {
    // 错误响应体是 Blob，解析其中的 detail 提示
    let detail = `导出失败（${e?.response?.status ?? ''}）`;
    try {
      if (e?.response?.data instanceof Blob) {
        const j = JSON.parse(await e.response.data.text());
        if (j?.detail) detail = j.detail;
      } else if (e?.response?.data?.detail) {
        detail = e.response.data.detail;
      }
    } catch { /* 解析失败用默认提示 */ }
    throw new Error(detail);
  }
  // [修正 2026-09-22] 改用公共 downloadBlob：原实现缺 appendChild，
  // 在 Firefox 下 click() 不会触发下载（表现为"点了没反应"），
  // 且 revoke 紧跟在 click 之后，大文件时可能尚未开始下载就失去数据源。
  // 本文件上方有一个同名的业务函数（带鉴权发起请求），故用别名引用公共工具
  downloadBlobCore(response.data as Blob, filename);
}

const SignageExport: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  // ===== 筛选条件 =====
  const [campus, setCampus] = useState<string>();
  const [building, setBuilding] = useState<string>();
  const [category, setCategory] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [search, setSearch] = useState<string>();

  // ===== 下拉选项数据 =====
  const [campuses, setCampuses] = useState<{ id: number; name: string }[]>([]);
  const [buildings, setBuildings] = useState<{ id: number; name: string }[]>([]);
  const [categories, setCategories] = useState<{ name: string }[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  // ===== 附件导出（[新增 2026-09-08] 两步式：生成任务 → 轮询 → 分卷下载） =====
  const [includeTypes, setIncludeTypes] = useState<string[]>(['design', 'photo', 'qrcode']);
  const [preparing, setPreparing] = useState(false);
  interface ExportPart { filename: string; size: number }
  interface ExportTask {
    task_id: string;
    status: 'processing' | 'done' | 'failed';
    created_at?: string;
    expires_at?: string;
    total?: number;
    counts?: { qrcode: number; design: number; photo: number; missing: number };
    parts?: ExportPart[];
    error?: string | null;
  }
  const [currentTask, setCurrentTask] = useState<ExportTask | null>(null);
  const [tasks, setTasks] = useState<ExportTask[]>([]);
  const pollRef = useRef<number | null>(null);

  // ===== 导入 =====
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    total: number; created: number; skipped: number; errors: string[];
  } | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  const [loading, setLoading] = useState(false);

  // 初始加载筛选选项：院区、分类
  useEffect(() => {
    setOptionsLoading(true);
    Promise.all([
      campusApi.getAllCampuses().catch(() => []),
      getActiveSignageCategories().catch(() => []),
    ])
      .then(([cps, cats]) => {
        setCampuses((cps as { id: number; name: string }[]) || []);
        setCategories((cats as { name: string }[]) || []);
      })
      .finally(() => setOptionsLoading(false));
  }, []);

  // 院区变化时加载该院区楼栋列表
  const campusId = useMemo(() => campuses.find((c) => c.name === campus)?.id, [campuses, campus]);
  useEffect(() => {
    setBuilding(undefined);
    setBuildings([]);
    if (!campusId) return;
    campusApi.getBuildings(campusId, 1, 200)
      .then((r) => setBuildings((r.items as { id: number; name: string }[]) || []))
      .catch(() => setBuildings([]));
  }, [campusId]);

  // 组装筛选查询串（导出数据与附件共用同一口径）
  const buildQuery = (extra: Record<string, string | boolean> = {}) => {
    const params = new URLSearchParams();
    if (campus) params.append('campus', campus);
    if (building) params.append('building', building);
    if (category) params.append('category', category);
    if (status) params.append('status', status);
    if (search?.trim()) params.append('search', search.trim());
    Object.entries(extra).forEach(([k, v]) => params.append(k, String(v)));
    return params.toString();
  };

  // 数据导出（xlsx / csv）
  const handleExport = async (format: 'xlsx' | 'csv') => {
    setLoading(true);
    try {
      await downloadBlob(`/api/signage-export/${format}?${buildQuery()}`, `标识台账.${format}`);
      message.success('导出成功');
    } catch (e: any) {
      message.error(getErrorMessage(e, '导出失败'));
    } finally {
      setLoading(false);
    }
  };

  // [新增 2026-09-08] 附件批量导出（两步式）：第一步生成后台打包任务并轮询状态；第二步按分卷下载
  const loadTasks = () => {
    api.get('/signage-export/attachments/tasks')
      .then((r) => setTasks(r.data || []))
      .catch(() => { /* 列表加载失败不打断页面 */ });
  };

  // 轮询当前任务状态，直至 done/failed
  const startPolling = (taskId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const r = await api.get(`/signage-export/attachments/status/${taskId}`);
        const t: ExportTask = r.data;
        setCurrentTask(t);
        if (t.status === 'done' || t.status === 'failed') {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
          loadTasks();
          if (t.status === 'done') message.success('压缩包生成完成，可下载');
          else message.error(t.error || '压缩包生成失败');
        }
      } catch {
        // 单次轮询失败忽略，下一轮继续
      }
    }, 2500);
  };

  const handlePrepareAttachments = async () => {
    if (includeTypes.length === 0) { message.warning('请至少选择一种附件类型'); return; }
    setPreparing(true);
    try {
      const r = await api.post(`/signage-export/attachments/prepare?${buildQuery({
        include_design: includeTypes.includes('design'),
        include_photo: includeTypes.includes('photo'),
        include_qrcode: includeTypes.includes('qrcode'),
      })}`);
      setCurrentTask(r.data);
      message.info('已开始生成压缩包，请稍候…');
      startPolling(r.data.task_id);
      loadTasks();
    } catch (e: any) {
      message.error(getErrorMessage(e, '创建打包任务失败'));
    } finally {
      setPreparing(false);
    }
  };

  const handleDownloadPart = async (taskId: string, filename: string) => {
    try {
      await downloadBlob(
        `/api/signage-export/attachments/download/${encodeURIComponent(taskId)}/${encodeURIComponent(filename)}`,
        filename,
      );
    } catch (e) {
      message.error(getErrorMessage(e, '下载失败'));
    }
  };

  /**
   * [新增 2026-09-22] 手动删除导出任务（连同已生成的压缩包）。
   *
   * 此前导出包只能等 24 小时保留期自动清理；若生成后立刻发现筛选条件选错，
   * 体积不小的压缩包会在磁盘上白占一天，用户也无法主动回收。
   */
  const handleDeleteTask = async (taskId: string) => {
    try {
      await api.delete(`/signage-export/attachments/${encodeURIComponent(taskId)}`);
      message.success('已删除该导出任务');
      loadTasks();
    } catch (e) {
      message.error(getErrorMessage(e, '删除失败'));
    }
  };

  // 卸载时停止轮询
  useEffect(() => () => {
    if (pollRef.current) window.clearInterval(pollRef.current);
  }, []);

  // 初始加载历史任务列表
  useEffect(() => { loadTasks(); }, []);

  // 下载导入模板
  const handleDownloadTemplate = async () => {
    try {
      await downloadBlob('/api/signage-export/import-template', '标识导入模板.xlsx');
    } catch (e: any) {
      message.error(getErrorMessage(e, '模板下载失败'));
    }
  };

  // 上传并导入
  const handleImport = async (file: File) => {
    setImporting(true);
    setImportResult(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      // [修复 2026-09-08] 改走 axios 客户端（原裸 fetch 读取错误的 'token' 键导致 401，且无静默刷新）
      const data = await api.post('/signage-export/import', fd).then((r) => r.data);
      setImportResult(data);
      message.success(`导入完成：成功 ${data.created} 条${data.errors?.length ? `，失败 ${data.errors.length} 条` : ''}`);
    } catch (e: any) {
      message.error(getErrorMessage(e, '导入失败'));
    } finally {
      setImporting(false);
      setFileList([]);
    }
    return false; // 阻止 antd Upload 自动上传
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      <Card title="筛选条件" loading={optionsLoading}>
        <Space wrap>
          <Select
            placeholder="院区" allowClear style={{ width: 180 }}
            value={campus} onChange={setCampus}
            options={campuses.map((c) => ({ value: c.name, label: c.name }))}
          />
          <Select
            placeholder="楼栋" allowClear style={{ width: 180 }}
            value={building} onChange={setBuilding}
            disabled={!campus}
            options={buildings.map((b) => ({ value: b.name, label: b.name }))}
          />
          <Select
            placeholder="分类" allowClear style={{ width: 180 }}
            value={category} onChange={setCategory}
            options={categories.map((c) => ({ value: c.name, label: c.name }))}
          />
          <Select
            placeholder="状态" allowClear style={{ width: 150 }}
            value={status} onChange={setStatus}
            options={SIGNAGE_STATUS_OPTIONS.map((s) => ({ value: s.value, label: s.label }))}
          />
          <Input
            placeholder="编码/名称关键词" allowClear style={{ width: 200 }}
            value={search} onChange={(e) => setSearch(e.target.value)}
          />
        </Space>
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            以下数据导出与附件导出均按当前筛选条件执行；楼栋选项需先选择院区。
          </Text>
        </div>
      </Card>

      <Card title="标识数据导出">
        <Space>
          <Button type="primary" icon={<FileExcelOutlined />} loading={loading} onClick={() => handleExport('xlsx')}>
            导出 Excel
          </Button>
          <Button icon={<FileTextOutlined />} loading={loading} onClick={() => handleExport('csv')}>
            导出 CSV
          </Button>
        </Space>
      </Card>

      {/* [重构 2026-09-08] 附件批量导出改为两步式：① 生成后台打包任务（单卷≤500MB 自动分卷）；② 按分卷下载。压缩包保留 24 小时 */}
      <Card title="附件批量导出（两步式：生成 → 下载）">
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Checkbox.Group
            value={includeTypes}
            onChange={(v) => setIncludeTypes(v as string[])}
            options={[
              { value: 'design', label: '设计文件（AI/PDF/图片）' },
              { value: 'photo', label: '安装现场照片' },
              { value: 'qrcode', label: '标识二维码（PNG）' },
            ]}
          />
          <div>
            <Button
              type="primary"
              icon={<FolderOpenOutlined />}
              loading={preparing || currentTask?.status === 'processing'}
              onClick={handlePrepareAttachments}
            >
              第一步：生成压缩包
            </Button>
          </div>
          {currentTask?.status === 'processing' && (
            <Space>
              <Spin size="small" />
              <Text type="secondary" style={{ fontSize: 12 }}>正在后台打包，可离开本页，完成后在下方列表下载…</Text>
            </Space>
          )}
          {currentTask?.status === 'failed' && (
            <Alert type="error" showIcon message={currentTask.error || '压缩包生成失败'} />
          )}
          <Text type="secondary" style={{ fontSize: 12 }}>
            单个压缩包不超过 500MB，超出自动分为多个分卷；压缩包保留 24 小时，到期自动清理。
            包内按「设计文件 / 现场照片 / 二维码」目录归类，文件名以标识编码开头，并附「导出清单.txt」。
          </Text>
        </Space>
      </Card>

      {/* 第二步：分卷下载列表 */}
      <Card title="第二步：下载压缩包（保留 24 小时）">
        {(() => {
          const doneTasks = [
            ...(currentTask && currentTask.status === 'done' ? [currentTask] : []),
            ...tasks.filter((t) => t.status === 'done' && t.task_id !== currentTask?.task_id),
          ];
          if (doneTasks.length === 0) {
            return <Text type="secondary">暂无可下载的压缩包，请先完成第一步生成。</Text>;
          }
          const humanSize = (n?: number) =>
            n == null ? '-' : n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {doneTasks.map((t) => (
                <div key={t.task_id} style={{ border: '1px solid var(--line-soft)', borderRadius: 8, padding: 12 }}>
                  <div style={{ marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 12, color: 'var(--text-2)', alignItems: 'center' }}>
                    <span>生成时间：{formatDateTimeStandard(t.created_at)}</span>
                    <span>标识数：{t.total ?? '-'}</span>
                    <span>
                      附件：二维码 {t.counts?.qrcode ?? 0} · 设计文件 {t.counts?.design ?? 0} · 现场照片 {t.counts?.photo ?? 0}
                    </span>
                    <span>保留至：{t.expires_at ? formatDateTimeStandard(t.expires_at) : '-'}</span>
                    {/* [新增 2026-09-22] 手动删除：此前只能等 24 小时到期自动清理，
                        生成后立刻发现选错条件时，压缩包要在磁盘上白占一天。
                        用 Popconfirm 二次确认 —— 删除会连同压缩包一起移除且不可恢复。 */}
                    <Popconfirm
                      title="删除该导出任务？"
                      description="将同时删除已生成的压缩包，操作不可恢复。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDeleteTask(t.task_id)}
                    >
                      <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        style={{ marginLeft: 'auto' }}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </div>
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    {(t.parts || []).map((p) => (
                      <Space key={p.filename} style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Text style={{ fontSize: 13 }}>{p.filename}（{humanSize(p.size)}）</Text>
                        <Button
                          size="small"
                          type="primary"
                          ghost
                          icon={<DownloadOutlined />}
                          onClick={() => handleDownloadPart(t.task_id, p.filename)}
                        >
                          下载
                        </Button>
                      </Space>
                    ))}
                  </Space>
                </div>
              ))}
            </div>
          );
        })()}
      </Card>

      <Card title="标识数据导入">
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Space>
            <Button icon={<FileAddOutlined />} onClick={handleDownloadTemplate}>
              下载导入模板
            </Button>
            <Upload
              accept=".xlsx"
              maxCount={1}
              fileList={fileList}
              beforeUpload={(file) => { handleImport(file); return false; }}
              onChange={({ fileList: fl }) => setFileList(fl)}
              onRemove={() => setFileList([])}
            >
              <Button type="primary" icon={<UploadOutlined />} loading={importing}>
                上传模板文件导入
              </Button>
            </Upload>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            「名称」「分类」为必填；编码留空时按「院区代号-分类编码-楼栋-楼层-序号」规则自动生成；编码已存在的行自动跳过；日期格式为 YYYY-MM-DD。
          </Text>
          {importResult && (
            <Alert
              type={importResult.errors.length ? 'warning' : 'success'}
              showIcon
              message={`导入完成：共 ${importResult.total} 行，成功 ${importResult.created} 条，跳过 ${importResult.skipped} 条，失败 ${importResult.errors.length} 条`}
              description={importResult.errors.length ? (
                <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                  {importResult.errors.map((err, i) => <div key={i} style={{ fontSize: 12 }}>{err}</div>)}
                </div>
              ) : undefined}
            />
          )}
        </Space>
      </Card>

      <Divider style={{ margin: 0 }} />
    </Space>
  );
};

export default SignageExport;
