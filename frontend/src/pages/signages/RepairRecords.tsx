// [新增 2026-09-09] 维修记录页（标识标记下方菜单）：
// 查看全部标识的全部维修记录，支持关键词/日期范围/维修部门/供应商/状态筛选；
// 导出前弹窗确认筛选范围（条数），可导出 Excel / CSV；维修前后照片缩略图可点击放大对比
import React, { useCallback, useEffect, useState } from 'react';
import { Card, Table, Button, Input, Select, DatePicker, Space, Tag, Modal, message, Image, Spin } from 'antd';
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

/** 带鉴权下载二进制流（导出接口返回文件流） */
async function downloadBlob(url: string, filename: string): Promise<void> {
  const response = await api.get(url.replace(/^\/api/, ''), { responseType: 'blob' });
  const blob = response.data as Blob;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

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

  const columns = [
    { title: '标识编码', dataIndex: 'code', key: 'code', width: 130 },
    { title: '标识名称', dataIndex: 'name', key: 'name', ellipsis: true, width: 160 },
    {
      title: '位置', key: 'location', ellipsis: true, width: 180,
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
          : <span style={{ color: '#97A3B2', fontSize: 12 }}>暂无现场照片</span>,
    },
    {
      title: '维修后照片', key: 'after', width: 100, align: 'center' as const,
      render: (_: unknown, r: SignageRepairListItem) =>
        r.repair_photo
          ? <Image src={getOriginalUrl(r.repair_photo) || ''} alt="维修后" width={48} height={48} style={{ objectFit: 'cover', borderRadius: 4 }} />
          : <span style={{ color: '#97A3B2', fontSize: 12 }}>暂无现场照片</span>,
    },
    {
      title: '发起', key: 'start', width: 170,
      render: (_: unknown, r: SignageRepairListItem) => (
        <span style={{ fontSize: 12 }}>
          {r.started_at ? formatDateTimeStandard(r.started_at) : '-'}
          <br />
          <span style={{ color: '#97A3B2' }}>{r.started_by || '未知'}</span>
        </span>
      ),
    },
    {
      title: '完成', key: 'done', width: 170,
      render: (_: unknown, r: SignageRepairListItem) => (
        <span style={{ fontSize: 12 }}>
          {r.completed_at ? formatDateTimeStandard(r.completed_at) : '-'}
          <br />
          <span style={{ color: '#97A3B2' }}>{r.completed_by || '-'}</span>
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
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          pagination={{
            current: page, pageSize, total,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
            showTotal: (t) => `共 ${t} 条`,
          }}
        />
      </Card>

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
        <ul style={{ fontSize: 13, color: '#5B6B7B' }}>
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
