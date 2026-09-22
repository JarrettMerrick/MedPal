// [新增 2026-09-09] 维修记录页（标识标记下方菜单）：
// 查看全部标识的全部维修记录，支持关键词/日期范围/维修部门/供应商/状态筛选；
// 导出前弹窗确认筛选范围（条数），可导出 Excel / CSV；维修前后照片缩略图可点击放大对比
import React, { useCallback, useEffect, useState } from 'react';
// 别名导入：本文件另有一个同名的业务函数（带鉴权发起请求后下载），
// 公共工具冲突，故用别名引用（见下方 downloadBlob 的说明）。
import { downloadBlob as downloadBlobCore } from '../../utils/fileUtils';
import { Card, Table, Button, Input, Select, DatePicker, Space, Tag, Modal, message, Image, Spin } from 'antd';
// [新增 2026-09-14] 标识编码跳转标识详情
import { Link } from 'react-router-dom';
import { SearchOutlined, ReloadOutlined, FileExcelOutlined, FileTextOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import api from '../../api/client';
import {
  getSignageRepairList, getSignageRepairCount, getRepairsExportUrl,
} from '../../api/signage';
import type { SignageRepairListItem, RepairListParams } from '../../api/signage';
import { getActiveSuppliers } from '../../api/signage-settings';
import type { Supplier } from '../../api/signage-settings';
import { getOriginalUrl } from '../../utils/imageUtils';
import { formatDateTimeStandard } from '../../utils/time';

const { RangePicker } = DatePicker;

/**
 * 带鉴权下载二进制流（导出接口返回文件流）。
 *
 * [修正 2026-09-22] 原先此处又写了一份自己的 Blob 下载实现 —— 全项目共有三份
 * （另两份在 utils/fileUtils 与 api/data）。三份写法**并不完全一致**，这正是
 * `api/audit.ts` 那份"少了一行 appendChild 导致 Firefox 下点了没反应"的成因。
 *
 * 现在只保留本函数的**业务部分**（携带 Bearer 令牌发起请求），
 * 把"生成并触发下载"这一步交给公共工具 downloadBlob —— 该工具的注释里写明了
 * 必须挂载到 DOM、以及 revoke 必须放在 click 之后的原因。
 *
 * 说明：本函数名保持不变（它描述的是"带鉴权的下载"这一业务动作，与公共工具
 * 的纯"触发下载"职责不同），因此无需改动任何调用点；公共工具以别名导入以免重名。
 */
async function downloadBlob(url: string, filename: string): Promise<void> {
  const response = await api.get(url.replace(/^\/api/, ''), { responseType: 'blob' });
  downloadBlobCore(response.data as Blob, filename);
}

// [修复 2026-09-19] 接入维修操作按钮。
// 历史原因：「标识预警」页下线时，其维修能力（发起维修 / 完成维修）约定并入本页，
// 共用组件 SignageRepairActions 也已建好，但**接入代码漏了** ——
// 结果是本项目任何页面都无法执行维修操作（无「标识维修」/「完成维修」按钮），
// 用户既发不起维修、也无法把「维修处理中」的记录更新为「已完成」。
import {
  useSignageRepairActions,
  SignageRepairButton,
  SignageCompleteButton,
} from '../../components/SignageRepairActions';

const RepairRecords: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<SignageRepairListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);

  // 筛选条件
  const [keyword, setKeyword] = useState('');
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [party, setParty] = useState<'vendor' | 'engineering' | undefined>();
  const [supplierId, setSupplierId] = useState<number | undefined>();
  const [status, setStatus] = useState<'in_progress' | 'completed' | undefined>();
  const [exporting, setExporting] = useState(false);
  const [exportModal, setExportModal] = useState<{ open: boolean; format: 'xlsx' | 'csv' | null }>({ open: false, format: null });

  useEffect(() => {
    getActiveSuppliers().then(setSuppliers).catch(() => setSuppliers([]));
  }, []);

  // 组装当前筛选参数（列表与导出共用同一口径）
  const buildParams = useCallback((): RepairListParams => ({
    keyword: keyword.trim() || undefined,
    start_date: range?.[0]?.format('YYYY-MM-DD'),
    end_date: range?.[1]?.format('YYYY-MM-DD'),
    repair_party: party,
    supplier_id: party === 'vendor' ? supplierId : undefined,
    status,
  }), [keyword, range, party, supplierId, status]);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getSignageRepairList({ page, page_size: pageSize, ...buildParams() });
      setItems(r.items);
      setTotal(r.total);
    } catch {
      message.error('获取维修记录失败');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, buildParams]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const handleSearch = () => { setPage(1); fetchList(); };

  const handleReset = () => {
    setKeyword('');
    setRange(null);
    setParty(undefined);
    setSupplierId(undefined);
    setStatus(undefined);
    setPage(1);
  };

  // 导出：先按筛选条件取总数，弹窗确认范围后下载
  const openExportModal = (format: 'xlsx' | 'csv') => {
    setExportModal({ open: true, format });
  };

  const [exportCount, setExportCount] = useState<number | null>(null);

  useEffect(() => {
    if (!exportModal.open) return;
    setExportCount(null);
    getSignageRepairCount(buildParams())
      .then((r) => setExportCount(r.total))
      .catch(() => setExportCount(null));
  }, [exportModal.open, buildParams]);

  const confirmExport = async () => {
    const format = exportModal.format;
    if (!format) return;
    setExporting(true);
    try {
      await downloadBlob(getRepairsExportUrl(buildParams(), format), `维修记录.${format}`);
      message.success('导出成功');
      setExportModal({ open: false, format: null });
    } catch {
      message.error('导出失败');
    } finally {
      setExporting(false);
    }
  };

  // [修复 2026-09-19] 维修操作：发起 / 完成维修成功后都刷新列表。
  // openRepair 打开「发起维修」弹窗（选择维修方、供应商、OA 单号）；
  // openComplete 打开「完成维修」弹窗（可附维修后照片）；modals 需在页面中渲染。
  const { openRepair, openComplete, modals, submitting } = useSignageRepairActions({
    onStarted: () => { fetchList(); },
    onCompleted: () => { fetchList(); },
  });

  const columns = [
    {
      // [调整 2026-09-14] 标识编码改为可点击链接，跳转该标识的详情页。
      // 用 Link 渲染真实 <a>，支持中键/Ctrl+点击在新标签页打开；
      // 列宽由 130 放宽到 150 以适应链接样式下的编码长度。
      title: '标识编码', dataIndex: 'code', key: 'code', width: 150,
      render: (code: string | undefined, r: SignageRepairListItem) =>
        code
          ? <Link to={`/signages/${r.signage_id}`}>{code}</Link>
          : '-',
    },
    // [调整 2026-09-19] 「标识名称」与「位置」去掉固定宽度，改为**自适应 + 允许换行**。
    // 本表原 11 列全部定宽（合计 1510px），没有任何列能伸缩 —— 容器不足时必然横向滚动。
    // 这两列是全表最长的文本列，让它们吸收/让出空间后，表格总宽可随容器收缩：
    // 宽屏各自展开、窄屏折行（不再截断，用户能看到完整名称与位置）。
    {
      title: '标识名称', dataIndex: 'name', key: 'name',
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 130 } as React.CSSProperties,
      }),
    },
    {
      title: '位置', key: 'location',
      onCell: () => ({
        style: { whiteSpace: 'normal', wordBreak: 'break-word', minWidth: 140 } as React.CSSProperties,
      }),
      render: (_: unknown, r: SignageRepairListItem) =>
        [r.campus, r.building, r.floor].filter(Boolean).join(' / ') || '-',
    },
    {
      title: '维修部门', dataIndex: 'party_label', key: 'party_label', width: 140,
      render: (v: string, r: SignageRepairListItem) => (
        <span>{v}{r.supplier_name ? `（${r.supplier_name}）` : ''}</span>
      ),
    },
    { title: 'OA单号', dataIndex: 'oa_number', key: 'oa_number', width: 130, render: (v?: string) => v || '-' },
    {
      title: '维修前照片', key: 'before', width: 100, align: 'center' as const,
      render: (_: unknown, r: SignageRepairListItem) =>
        r.repair_photo_before
          ? <Image src={getOriginalUrl(r.repair_photo_before) || ''} alt="维修前" width={48} height={48} style={{ objectFit: 'cover', borderRadius: 4 }} />
          : <span style={{ color: 'var(--text-3)', fontSize: 12 }}>暂无现场照片</span>,
    },
    {
      title: '维修后照片', key: 'after', width: 100, align: 'center' as const,
      render: (_: unknown, r: SignageRepairListItem) =>
        r.repair_photo
          ? <Image src={getOriginalUrl(r.repair_photo) || ''} alt="维修后" width={48} height={48} style={{ objectFit: 'cover', borderRadius: 4 }} />
          : <span style={{ color: 'var(--text-3)', fontSize: 12 }}>暂无现场照片</span>,
    },
    {
      title: '发起', key: 'start', width: 170,
      render: (_: unknown, r: SignageRepairListItem) => (
        <span style={{ fontSize: 12 }}>
          {r.started_at ? formatDateTimeStandard(r.started_at) : '-'}
          <br />
          <span style={{ color: 'var(--text-3)' }}>{r.started_by || '未知'}</span>
        </span>
      ),
    },
    {
      title: '完成', key: 'done', width: 170,
      render: (_: unknown, r: SignageRepairListItem) => (
        <span style={{ fontSize: 12 }}>
          {r.completed_at ? formatDateTimeStandard(r.completed_at) : '-'}
          <br />
          <span style={{ color: 'var(--text-3)' }}>{r.completed_by || '-'}</span>
        </span>
      ),
    },
    {
      title: '时长(小时)', dataIndex: 'duration_hours', key: 'duration', width: 100,
      render: (v?: number | null) => (v === null || v === undefined ? '-' : v),
    },
    {
      title: '状态', dataIndex: 'status_label', key: 'status', width: 110,
      render: (v: string, r: SignageRepairListItem) => (
        <Tag color={r.status === 'completed' ? 'green' : 'processing'}>{v}</Tag>
      ),
    },
    {
      // [修复 2026-09-19] 新增「操作」列，按**三种**状态分别呈现。
      //
      // ⚠️ 上一版的错误：只判断了 in_progress，其余一律走 else 显示"已完成" ——
      // 而后端实际有三种状态（见 signage_repair_service.REPAIR_STATUS_LABELS）：
      //     pending      待维修       ← 标识已损坏、尚未发起维修
      //     in_progress  维修处理中
      //     completed    已完成
      // 结果「待维修」的行被错误地显示为"已完成"，且用户没有任何发起维修的入口。
      //
      // 现在：
      //   pending      → 「标识维修」按钮（发起维修）
      //   in_progress  → 「完成维修」按钮
      //   completed    → 文字提示
      title: '操作', key: 'actions', width: 140,
      render: (_: unknown, r: SignageRepairListItem) => {
        if (r.status === 'pending') {
          // 待维修行的 id 由后端复用**标识 id**（见 _pending_to_item），
          // 因此发起维修用 signage_id（回退到 id 以兼容两种数据来源）。
          return (
            <SignageRepairButton
              onClick={() =>
                openRepair({
                  signage_id: r.signage_id || r.id,
                  name: r.name,
                  code: r.code,
                })
              }
              disabled={submitting}
            />
          );
        }
        if (r.status === 'in_progress') {
          return (
            <SignageCompleteButton
              onClick={() =>
                openComplete({
                  repair_id: r.id,
                  signage_id: r.signage_id,
                  name: r.name,
                  code: r.code,
                })
              }
              disabled={submitting}
            />
          );
        }
        return <span style={{ color: 'var(--text-3)', fontSize: 12 }}>已完成</span>;
      },
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            allowClear
            placeholder="标识编码 / 名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 200 }}
          />
          <RangePicker
            value={range}
            onChange={(d) => setRange(d as [Dayjs, Dayjs] | null)}
            placeholder={['发起时间起', '发起时间止']}
          />
          <Select
            allowClear
            placeholder="维修部门"
            style={{ width: 150 }}
            value={party}
            onChange={(v) => { setParty(v); if (v !== 'vendor') setSupplierId(undefined); }}
            options={[
              { value: 'engineering', label: '工程部维修' },
              { value: 'vendor', label: '供应商维修' },
            ]}
          />
          {party === 'vendor' && (
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择供应商"
              style={{ width: 200 }}
              value={supplierId}
              onChange={setSupplierId}
              options={suppliers.map((s) => ({ value: s.id, label: s.name }))}
            />
          )}
          <Select
            allowClear
            placeholder="维修状态"
            style={{ width: 150 }}
            value={status}
            onChange={setStatus}
            options={[
              { value: 'in_progress', label: '维修处理中' },
              { value: 'completed', label: '已完成' },
            ]}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
          <Button icon={<ReloadOutlined />} onClick={handleReset}>重置</Button>
          <Button icon={<FileExcelOutlined />} onClick={() => openExportModal('xlsx')}>导出 Excel</Button>
          <Button icon={<FileTextOutlined />} onClick={() => openExportModal('csv')}>导出 CSV</Button>
        </Space>
      </Card>

      <Card title={`维修记录（共 ${total} 条）`}>
        <Table
          columns={columns}
          dataSource={items}
          // [修复 2026-09-19] rowKey 由 "id" 改为「状态 + id」的复合键：
          // 本列表混排两类数据 —— 「待维修」行（pending）的 id 由后端复用**标识 id**，
          // 而维修记录行的 id 是**维修记录 id**，两者取值空间重叠，
          // 只用 id 作 key 会出现重复键，导致行复用错乱（勾选/展开错位）。
          rowKey={(r) => `${r.status}-${r.id}`}
          loading={loading}
          // [调整 2026-09-19] 移除 scroll={{ x: 1400 }}：
          // 该配置会**强制**表格出现横向滚动条（内容不足 1400px 时也保留占位），
          // 与「表格整体不出现横向滚动条」的要求冲突。
          // 去掉后由 table-layout: auto 按内容分配列宽，超长文本在单元格内换行；
          // 配合全局 .ant-table-wrapper table{width:100%} 保证总宽恒等于容器。
          scroll={{ x: 'max-content' }}
          pagination={{
            current: page, pageSize, total,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
            showTotal: (t) => `共 ${t} 条`,
          }}
        />
      </Card>

      {/* [修复 2026-09-19] 渲染维修操作弹窗（完成维修 / 照片上传）——
          必须挂载在页面中，否则点击操作列的按钮不会有任何反应 */}
      {modals}

      {/* 导出确认弹窗：展示当前筛选范围与条数 */}
      <Modal
        title="确认导出范围"
        open={exportModal.open}
        onOk={confirmExport}
        onCancel={() => setExportModal({ open: false, format: null })}
        confirmLoading={exporting}
        okText="确认导出"
        cancelText="取消"
      >
        <p>将按当前筛选条件导出维修记录（{exportModal.format === 'xlsx' ? 'Excel' : 'CSV'}）：</p>
        <ul style={{ fontSize: 13, color: 'var(--text-2)' }}>
          <li>关键词：{keyword.trim() || '不限'}</li>
          <li>日期范围：{range ? `${range[0].format('YYYY-MM-DD')} ~ ${range[1].format('YYYY-MM-DD')}` : '不限'}</li>
          <li>维修部门：{party === 'vendor' ? `供应商维修${supplierId ? `（${suppliers.find((s) => s.id === supplierId)?.name || ''}）` : ''}` : party === 'engineering' ? '工程部维修' : '不限'}</li>
          <li>维修状态：{status === 'in_progress' ? '维修处理中' : status === 'completed' ? '已完成' : '不限'}</li>
        </ul>
        <p style={{ marginTop: 12 }}>
          预计导出条数：
          {exportCount === null ? <Spin size="small" /> : <b>{exportCount}</b>}
        </p>
      </Modal>
    </div>
  );
};

export default RepairRecords;
