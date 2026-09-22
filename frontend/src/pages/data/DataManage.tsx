// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 数据管理（导出/导入/备份恢复 + 图片打包）。
 * [改进] 手写 tabs/section/select → Tabs/Card/Select/Button/Alert
 */

import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Tabs, Card, Button, Select, Checkbox, Typography, Row, Col, Space, Alert, App, Tag, Modal, Input, Spin, Progress, Table, DatePicker, type TableProps } from 'antd';
import { DownloadOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { exportStaff, exportDepartments, exportRegulations, importStaff, importDepartments, importRegulations, importPhotos, templateStaff, templateDepartments, templateRegulations, backupDatabase, getBackupList, restoreBackup, uploadRestoreBackup, downloadBackupFn, deleteBackup, createPackage, getPackageList, downloadPackage, deletePackage, verifyStaff } from '../../api/data';
import type { PackageItem, StaffVerifyItem } from '../../api/data';
// [修复 2026-09-01] 新增系统日志 API 导入
import { getSystemLogs, exportSystemLogs, cleanupSystemLogs } from '../../api/audit';
import type { SystemLogItem } from '../../api/audit';
import { hasPermission, PERM_STAFF_EDIT, PERM_SYSTEM_AUDIT } from '../../utils/permissions';
import { formatDateTime } from '../../utils/time';
import { getAllDepartments } from '../../api/departments';
import { WORK_TYPE_OPTIONS, WORK_TYPE_COLOR, WORK_TYPE_LABELS } from '../../types/staff';
import { formatSize } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
// [改进 2026-09-21 / Q-12] 统一错误文案提取：把 `e?.response?.data?.detail || '默认'`
// 收敛为 getErrorMessage(e, '默认')，类型由 unknown 收窄，字段名写错会在编译期报错。
import { getErrorMessage } from '../../api/client';
// [修复 2026-09-17] 功能开关：「制度牌」关闭后隐藏本页的制度导出/导入入口
// （后端对应接口会返回 403，前端隐藏以保持口径一致）
import { useFeatures } from '../../contexts/FeaturesContext';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
// [修复 2026-09-03] 导入标识数据导出组件
import SignageExport from '../signages/SignageExport';

const { Text } = Typography;
interface BackupItem { filename: string; size: number; created_at: string; modified_at: string; }

const STAFF_FIELDS = [
  { key: 'employee_id', label: '工号' }, { key: 'name', label: '姓名' }, { key: 'work_type', label: '工种' },
  { key: 'education', label: '学历' }, { key: 'title', label: '职称' }, { key: 'department', label: '所属部门' },
  { key: 'position', label: '职务' }, { key: 'status', label: '状态' },
  { key: 'expertise_short', label: '专业擅长（短）' }, { key: 'expertise_standard', label: '专业擅长（标准）' },
  { key: 'social_appointments', label: '社会任职' }, { key: 'honors', label: '获得荣誉' }, { key: 'remarks', label: '备注' },
];

const DataManage: React.FC = () => {
  const { modal } = App.useApp();
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  // [改进] 方案A：导入互斥锁（importing 非空时拒绝新导入）与上传进度（0-100），
  // 防止用户误以为无反应而重复提交，导致并发写库崩溃
  const [importing, setImporting] = useState<string | null>(null);
  const [importProgress, setImportProgress] = useState(0);
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);
  const [expWorkType, setExpWorkType] = useState('');
  const [expDept, setExpDept] = useState('');
  const [expStatus, setExpStatus] = useState('');
  const [expFields, setExpFields] = useState<string[]>(STAFF_FIELDS.map(f => f.key));
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [packages, setPackages] = useState<PackageItem[]>([]);
  const [pkgDeptId, setPkgDeptId] = useState<number | ''>('');
  // [修复 2026-08-28] 图片打包照片类型筛选（front=正面照/side=侧面照/card=卡片照），默认全选
  const [pkgPhotoTypes, setPkgPhotoTypes] = useState<string[]>(['front', 'side', 'card']);
  const PHOTO_TYPE_OPTIONS = [
    { value: 'front', label: '正面照' },
    { value: 'side', label: '侧面照' },
    { value: 'card', label: '卡片照' },
  ];
  const staffRef = useRef<HTMLInputElement>(null);
  const deptRef = useRef<HTMLInputElement>(null);
  const regRef = useRef<HTMLInputElement>(null);
  const photoRef = useRef<HTMLInputElement>(null);
  const uploadRestoreRef = useRef<HTMLInputElement>(null);
  // [修复] 上传恢复需二次密码确认：新增密码输入弹窗状态，
  // 后端 restore_upload_database 校验 confirm_password，原先前端 modal.confirm
  // 无密码输入框导致 confirm_password 为空，始终返回 403
  const [restoreModalOpen, setRestoreModalOpen] = useState(false);
  const [restorePassword, setRestorePassword] = useState('');
  const [restoreSubmitting, setRestoreSubmitting] = useState(false);
  const [restoreProgress, setRestoreProgress] = useState(0);
  const [pendingRestoreFile, setPendingRestoreFile] = useState<File | null>(null);
  // [修复 2026-09-01] 新增数据核对功能状态：筛选条件、仅显示缺失开关、核对结果与分页
  const navigate = useNavigate();
  const { user } = useAuth();
  // [修复 2026-09-17] 单位级功能开关：用于隐藏被关闭模块的相关入口（当前用于「制度牌」）
  const { isEnabled } = useFeatures();
  const canEditStaff = hasPermission(user, PERM_STAFF_EDIT);
  const VERIFY_WORK_TYPE_OPTIONS = WORK_TYPE_OPTIONS.filter(o => o.value !== 'admin');
  const [verifyPage, setVerifyPage] = useState(1);
  const [verifyWorkType, setVerifyWorkType] = useState('');
  const [verifyDept, setVerifyDept] = useState('');
  const [verifyStatus, setVerifyStatus] = useState('active');
  const [verifyOnlyMissing, setVerifyOnlyMissing] = useState(true);
  const [verifyData, setVerifyData] = useState<StaffVerifyItem[]>([]);
  const [verifyTotal, setVerifyTotal] = useState(0);
  const [verifyMissingTotal, setVerifyMissingTotal] = useState(0);
  const [verifyLoading, setVerifyLoading] = useState(false);

  // [修复 2026-09-01] 新增系统日志功能状态
  const canViewAudit = hasPermission(user, PERM_SYSTEM_AUDIT);
  const [sysLogPage, setSysLogPage] = useState(1);
  const [sysLogCategory, setSysLogCategory] = useState('');
  const [sysLogLevel, setSysLogLevel] = useState('');
  const [sysLogKeyword, setSysLogKeyword] = useState('');
  const [sysLogStartDate, setSysLogStartDate] = useState<string | null>(null);
  const [sysLogEndDate, setSysLogEndDate] = useState<string | null>(null);
  const [sysLogData, setSysLogData] = useState<SystemLogItem[]>([]);
  const [sysLogTotal, setSysLogTotal] = useState(0);
  const [sysLogLoading, setSysLogLoading] = useState(false);
  const [sysLogCleanupDays, setSysLogCleanupDays] = useState(90);

  const show = (type: 'success' | 'error', msg: string) => { setFeedback({ type, msg }); setTimeout(() => setFeedback(null), 5000); };

  // [修复 2026-09-01] 数据核对：调用 /api/data/verify-staff 获取信息不完整的人员列表
  const loadVerify = async (page: number = 1) => {
    setVerifyLoading(true);
    try {
      const r = await verifyStaff({
        page,
        page_size: 20,
        work_type: verifyWorkType || undefined,
        department: verifyDept || undefined,
        status: verifyStatus || undefined,
        only_missing: verifyOnlyMissing,
      });
      setVerifyData(r.items);
      setVerifyTotal(r.total);
      setVerifyMissingTotal(r.missing_total);
      setVerifyPage(page);
    } catch (e: any) {
      show('error', e?.response?.data?.detail || '数据核对失败');
    } finally {
      setVerifyLoading(false);
    }
  };

  const verifyColumns: TableProps<StaffVerifyItem>['columns'] = [
    { title: '工号', dataIndex: 'employee_id', width: 100 },
    { title: '姓名', dataIndex: 'name', width: 110 },
    {
      title: '工种', dataIndex: 'work_type', width: 80,
      render: (wt: string) => <Tag color={WORK_TYPE_COLOR[wt]}>{WORK_TYPE_LABELS[wt] || wt}</Tag>,
    },
    { title: '科室', dataIndex: 'department', ellipsis: true },
    {
      title: '缺失项',
      dataIndex: 'missing_labels',
      render: (labels: string[]) =>
        labels.length > 0
          ? labels.map(l => <Tag key={l} color="error" style={{ marginBottom: 2 }}>{l}未填</Tag>)
          : <Tag color="success">信息完整</Tag>,
    },
  ];
  if (canEditStaff) {
    verifyColumns.push({
      title: '操作',
      width: 90,
      render: (_: unknown, record: StaffVerifyItem) => (
        <Button type="link" size="small" onClick={() => navigate(`/staff/edit/${record.employee_id}`)}>去完善</Button>
      ),
    });
  }

  // [修复 2026-09-01] 系统日志：调用 /api/audit/system-logs 获取日志列表
  const loadSysLogs = async (page: number = 1) => {
    setSysLogLoading(true);
    try {
      const r = await getSystemLogs({
        page, page_size: 20,
        category: sysLogCategory || undefined,
        level: sysLogLevel || undefined,
        keyword: sysLogKeyword || undefined,
        start_date: sysLogStartDate || undefined,
        end_date: sysLogEndDate || undefined,
      });
      setSysLogData(r.items);
      setSysLogTotal(r.total);
      setSysLogPage(page);
    } catch (e: any) {
      show('error', e?.response?.data?.detail || '加载系统日志失败');
    } finally {
      setSysLogLoading(false);
    }
  };

  const handleExportSysLogs = async () => {
    try {
      await exportSystemLogs({
        category: sysLogCategory || undefined,
        level: sysLogLevel || undefined,
        keyword: sysLogKeyword || undefined,
        start_date: sysLogStartDate || undefined,
        end_date: sysLogEndDate || undefined,
      });
      show('success', '导出完成');
    } catch (e: any) {
      show('error', e?.response?.data?.detail || '导出失败');
    }
  };

  const handleCleanupSysLogs = async () => {
    modal.confirm({
      title: `确定清理 ${sysLogCleanupDays} 天前的日志？`,
      // [新增 2026-09-19] 明确告知不可逆与留痕：清理等同删除审计痕迹，
      // 属最敏感操作之一，二次确认需让操作者知晓后果。
      content: '清理将永久删除该时间之前的审计记录，无法恢复；该操作本身也会记入审计。请确认已完成必要的备份或导出。',
      okType: 'danger',
      onOk: async () => {
        try {
          const r = await cleanupSystemLogs(sysLogCleanupDays);
          show('success', r.message);
          loadSysLogs(1);
        } catch (e: any) {
          show('error', e?.response?.data?.detail || '清理失败');
        }
      },
    });
  };

  const LEVEL_COLOR: Record<string, string> = { INFO: 'blue', WARN: 'orange', ERROR: 'red' };
  const CATEGORY_COLOR: Record<string, string> = { operation: 'cyan', system: 'geekblue', error: 'volcano' };

  const sysLogColumns: TableProps<SystemLogItem>['columns'] = [
    { title: '时间', dataIndex: 'timestamp', width: 170, render: (v: string) => formatDateTime(v) },
    { title: '级别', dataIndex: 'level', width: 80, render: (v: string) => <Tag color={LEVEL_COLOR[v]}>{v}</Tag> },
    { title: '类别', dataIndex: 'category_label', width: 100, render: (v: string, r: SystemLogItem) => <Tag color={CATEGORY_COLOR[r.category]}>{v}</Tag> },
    { title: '操作人', dataIndex: 'operator_name', width: 100 },
    { title: '内容', dataIndex: 'content', ellipsis: true },
    { title: 'IP', dataIndex: 'ip_address', width: 130 },
  ];

  useEffect(() => {
    getAllDepartments().then(list => { setDepartments(list); if (list.length > 0 && pkgDeptId === '') setPkgDeptId(list[0].id); }).catch(() => {});
    // [改进] 页面挂载即拉取打包记录，避免刷新后列表空白（旧逻辑仅在创建打包或切换 Tab 时才刷新）。
    refreshPackages();
    refreshBackups();
  }, []);

  const refreshBackups = () => { getBackupList().then(setBackups).catch(() => {}); };
  const refreshPackages = () => { getPackageList().then(setPackages).catch(() => {}); };

  // [改进] 方案A：导入互斥锁 + 长超时请求 + 上传进度回调。
  // 上传阶段显示真实百分比；上传完成后进入后端解析写库阶段，界面提示请勿重复操作。
  const handleImport = async (file: File | undefined, handler: (f: File, onProgress?: (p: number) => void) => Promise<any>, label: string) => {
    if (!file || importing) return;
    setImporting(label);
    setImportProgress(0);
    try {
      const r = await handler(file, (p) => setImportProgress(p));
      let msg = r.message || '导入成功';
      if (r.warnings?.length > 0) msg += `\n⚠️ ${r.warnings.length} 条警告：${r.warnings.slice(0, 3).join('；')}${r.warnings.length > 3 ? '...' : ''}`;
      show(r.warnings?.length > 0 ? 'error' : 'success', msg);
    } catch (e) { show('error', getErrorMessage(e, '导入失败')); }
    finally { setImporting(null); setImportProgress(0); }
  };

  const handleRestore = (filename: string) => {
    modal.confirm({
      title: `确定恢复 ${filename}？当前数据将被覆盖！`,
      okType: 'danger',
      onOk: async () => {
        try { await restoreBackup(filename); show('success', '恢复成功'); refreshBackups(); } catch (e: any) { show('error', e?.response?.data?.detail || '恢复失败'); }
      },
    });
  };

  const handleDeleteBackup = (filename: string) => {
    modal.confirm({
      title: `确定删除 ${filename}？`,
      onOk: async () => { try { await deleteBackup(filename); show('success', '已删除'); refreshBackups(); } catch (e: any) { show('error', e?.response?.data?.detail || '删除失败'); } },
    });
  };

  const exportTab = (
    <div>
      {/* 人员信息导出 */}
      <Card title={<><span style={{ marginRight: 8 }}>👥</span>人员信息导出</>} style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          <Col xs={24} sm={8}><Select value={expWorkType || undefined} onChange={setExpWorkType} placeholder="全部工种" style={{ width: '100%' }} allowClear options={[...WORK_TYPE_OPTIONS]} /></Col>
          <Col xs={24} sm={8}><Select value={expDept || undefined} onChange={setExpDept} placeholder="全部科室" style={{ width: '100%' }} allowClear options={departments.map(d => ({ value: d.name, label: d.name }))} /></Col>
          <Col xs={24} sm={8}><Select value={expStatus || undefined} onChange={setExpStatus} placeholder="全部状态" style={{ width: '100%' }} allowClear options={[{ value: 'active', label: '在职' }, { value: 'resigned', label: '离职' }]} /></Col>
        </Row>
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>导出字段</Text>
            <Space size={4}><Button type="link" size="small" onClick={() => setExpFields(STAFF_FIELDS.map(f => f.key))}>全选</Button><Button type="link" size="small" onClick={() => setExpFields(['employee_id', 'name', 'work_type', 'department'])}>仅基本信息</Button></Space>
          </div>
          <Checkbox.Group value={expFields} onChange={vals => setExpFields(vals as string[])}>
            <Row gutter={[8, 4]}>
              {STAFF_FIELDS.map(f => <Col key={f.key}><Checkbox value={f.key}>{f.label}</Checkbox></Col>)}
            </Row>
          </Checkbox.Group>
        </div>
        <Button type="primary" loading={loading === 'export-staff'} icon={<DownloadOutlined />} onClick={async () => {
          setLoading('export-staff');
          try { await exportStaff({ work_type: expWorkType || undefined, department: expDept || undefined, status: expStatus || undefined, fields: expFields.join(',') }); show('success', '导出完成'); }
          catch (e) { show('error', getErrorMessage(e, '导出失败')); }
          finally { setLoading(null); }
        }}>导出人员信息</Button>
      </Card>

      {/* 科室导出 */}
      <Card title={<><span style={{ marginRight: 8 }}>🏥</span>科室信息导出</>} style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>导出所有科室基本信息、特色技术、特色设备</Text>
        <Button type="primary" loading={loading === 'export-dept'} icon={<DownloadOutlined />} onClick={async () => {
          setLoading('export-dept'); try { await exportDepartments(); show('success', '导出完成'); } catch (e: any) { show('error', e?.response?.data?.detail || '导出失败'); } finally { setLoading(null); }
        }}>导出科室信息</Button>
      </Card>

      {/* 制度导出（[修复 2026-09-17] 受「制度牌」功能开关约束：关闭后不显示入口） */}
      {isEnabled('regulation') && (
        <Card title={<><span style={{ marginRight: 8 }}>📋</span>制度信息导出</>} style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>导出所有制度名称、类别、版本及时间信息</Text>
          <Button type="primary" loading={loading === 'export-reg'} icon={<DownloadOutlined />} onClick={async () => {
            setLoading('export-reg'); try { await exportRegulations(); show('success', '导出完成'); } catch (e: any) { show('error', e?.response?.data?.detail || '导出失败'); } finally { setLoading(null); }
          }}>导出制度信息</Button>
        </Card>
      )}

      {/* 图片打包 */}
      <Card title={<><span style={{ marginRight: 8 }}>🖼️</span>图片打包</>}>
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>照片类型（可单选或多选，缺省全部导出）</Text>
          <Checkbox.Group
            options={PHOTO_TYPE_OPTIONS}
            value={pkgPhotoTypes}
            onChange={vals => setPkgPhotoTypes(vals as string[])}
          />
        </div>
        <Space style={{ marginBottom: 12 }}>
          <Select value={pkgDeptId as number} onChange={v => setPkgDeptId(v)} options={departments.map(d => ({ value: d.id, label: d.name }))} style={{ minWidth: 160 }} />
          <Button type="primary" icon={<PlusOutlined />} disabled={pkgPhotoTypes.length === 0} onClick={async () => {
            try { const r = await createPackage(pkgDeptId as number, pkgPhotoTypes); show('success', r.message); refreshPackages(); } catch (e: any) { show('error', e?.response?.data?.detail || '打包失败'); }
          }}>创建打包</Button>
        </Space>
        {packages.map(p => (
          <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--neu-page-bg)', borderRadius: 8, marginBottom: 4, fontSize: 13 }}>
            <Space>
              <Text strong>{p.department_name}</Text>
              <Tag color={p.status === 'completed' ? 'green' : p.status === 'packing' ? 'gold' : 'red'}>{({ packing: '打包中', completed: '完成', expired: '已过期', failed: '失败' })[p.status]}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>{formatSize(p.file_size)}</Text>
            </Space>
            <Space size={4}>
              {p.status === 'completed' && <Button size="small" onClick={() => downloadPackage(p.id, p.filename)}>下载</Button>}
              <Button size="small" danger onClick={() => deletePackage(p.id).then(refreshPackages)}>删除</Button>
            </Space>
          </div>
        ))}
      </Card>
    </div>
  );

  const importTab = (
    <div>
      {importing && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="正在导入数据，请勿重复操作或关闭页面…"
          description={importProgress > 0 && importProgress < 100 ? `文件上传中：${importProgress}%（请勿重复上传）` : '文件上传完成，正在解析并写入数据库，请耐心等待…'}
        />
      )}
      {[
        { icon: '👥', title: '人员信息导入', tplFn: templateStaff, ref: staffRef, handler: importStaff, label: 'staff', desc: '下载模板填写后上传。已存在工号的员工将被跳过。' },
        { icon: '🏥', title: '科室信息导入', tplFn: templateDepartments, ref: deptRef, handler: importDepartments, label: 'dept', desc: '支持三张工作表：科室信息、特色技术、特色设备。' },
        { icon: '📋', title: '制度信息导入', tplFn: templateRegulations, ref: regRef, handler: importRegulations, label: 'reg', desc: '包含制度名称、所属类别、类别代码、制度内容。版本号自动生成。' },
      ]
        // [修复 2026-09-17] 「制度牌」开关关闭时不下发制度导入入口
        .filter(item => item.label !== 'reg' || isEnabled('regulation'))
        .map(item => (
        <Card key={item.label} title={<>{item.icon} {item.title}</>} style={{ marginBottom: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>{item.desc}</Text>
          <Space>
            <Button icon={<DownloadOutlined />} disabled={importing !== null} onClick={() => item.tplFn()}>下载模板</Button>
            <label style={{ display: 'inline-flex', alignItems: 'center', padding: '4px 16px', background: '#ED7B2F', color: '#fff', borderRadius: 8, cursor: importing ? 'not-allowed' : 'pointer', fontSize: 13, opacity: importing && importing !== item.label ? 0.55 : 1 }}>
              {importing === item.label ? (
                <><Spin size="small" style={{ color: '#fff', marginRight: 8 }} />{importProgress > 0 && importProgress < 100 ? `上传中 ${importProgress}%` : '正在解析并写入数据…'}</>
              ) : '上传文件导入'}
              <input type="file" accept=".xlsx,.xls" hidden disabled={importing !== null} ref={item.ref} onChange={e => { handleImport(e.target.files?.[0], item.handler, item.label); e.target.value = ''; }} />
            </label>
          </Space>
        </Card>
      ))}
      {/* 照片批量导入 */}
      <Card title="📸 照片批量导入" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
          上传 ZIP 压缩包，内含照片文件。命名规则：{'{'}工号{'}'}_{'{'}front|side|card{'}'}.{'{'}ext{'}'}。支持 jpg/png/webp。
        </Text>
        <label style={{ display: 'inline-flex', alignItems: 'center', padding: '4px 16px', background: '#ED7B2F', color: '#fff', borderRadius: 8, cursor: importing ? 'not-allowed' : 'pointer', fontSize: 13, opacity: importing && importing !== 'photo' ? 0.55 : 1 }}>
          {importing === 'photo' ? (
            <><Spin size="small" style={{ color: '#fff', marginRight: 8 }} />{importProgress > 0 && importProgress < 100 ? `上传中 ${importProgress}%` : '正在解析并写入数据…'}</>
          ) : '选择ZIP文件导入'}
          <input type="file" accept=".zip" hidden disabled={importing !== null} ref={photoRef} onChange={e => { handleImport(e.target.files?.[0], importPhotos, 'photo'); e.target.value = ''; }} />
        </label>
      </Card>
    </div>
  );

  const backupTab = (
    <div>
      <Card title="💾 手动备份" style={{ marginBottom: 16 }}>
        <Button type="primary" loading={loading === 'backup'} onClick={async () => {
          setLoading('backup'); try { const r = await backupDatabase(); show('success', `备份完成: ${r.filename} (${formatSize(r.size)})`); refreshBackups(); } catch (e: any) { show('error', e?.response?.data?.detail || '备份失败'); } finally { setLoading(null); }
        }}>立即备份</Button>
      </Card>

      <Card title="📁 备份列表" style={{ marginBottom: 16 }}>
        {backups.length === 0 ? <Text type="secondary">暂无备份</Text> : backups.map(b => (
          <div key={b.filename} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'var(--neu-page-bg)', borderRadius: 8, marginBottom: 4, fontSize: 13 }}>
            <div><Text strong style={{ display: 'block' }}>{b.filename}</Text><Text type="secondary" style={{ fontSize: 12 }}>{formatSize(b.size)} · {b.created_at}</Text></div>
            <Space size={4}>
              <Button size="small" onClick={() => downloadBackupFn(b.filename)}>下载</Button>
              <Button size="small" onClick={() => handleRestore(b.filename)}>恢复</Button>
              <Button size="small" danger onClick={() => handleDeleteBackup(b.filename)}>删除</Button>
            </Space>
          </div>
        ))}
      </Card>

      <Card title="📤 上传恢复">
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>上传 .db 备份文件恢复数据库</Text>
        <label style={{ display: 'inline-flex', alignItems: 'center', padding: '6px 16px', background: '#ED7B2F', color: '#fff', borderRadius: 8, cursor: 'pointer', fontSize: 13 }}>
          上传并恢复
          <input type="file" accept=".db" hidden ref={uploadRestoreRef} onChange={e => {
            const f = e.target.files?.[0]; if (!f) return;
            // [修复] 选择文件后打开密码确认弹窗（后端要求二次密码确认），
            // 原先直接 modal.confirm 无密码输入框，confirm_password 为空必然 403
            setPendingRestoreFile(f);
            setRestorePassword('');
            setRestoreModalOpen(true);
            e.target.value = '';
          }} />
        </label>
      </Card>
    </div>
  );

  // [修复 2026-09-01] 新增数据核对 Tab：筛选医生/护士/技师中信息未填写完整的人员
  const verifyTab = (
    <div>
      <Card title={<><span style={{ marginRight: 8 }}>✅</span>数据核对</>} style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
          核对医生/护士/技师的信息完整性。医生须填写：姓名、职称、专业擅长（短）、专业擅长（标准）、个人照片、卡片照片；
          护士、技师须填写：姓名、职称、照片、卡片照片（不审核专业擅长）。未填写项会以红色标签展示。
          个人照片：正面照或侧面照只要有一张即视为已填写。
        </Text>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          <Col xs={24} sm={8}>
            <Select value={verifyWorkType || undefined} onChange={v => setVerifyWorkType(v || '')} placeholder="全部工种" style={{ width: '100%' }} allowClear options={VERIFY_WORK_TYPE_OPTIONS} />
          </Col>
          <Col xs={24} sm={8}>
            <Select value={verifyDept || undefined} onChange={v => setVerifyDept(v || '')} placeholder="全部科室" style={{ width: '100%' }} allowClear options={departments.map(d => ({ value: d.name, label: d.name }))} />
          </Col>
          <Col xs={24} sm={8}>
            <Space wrap>
              <Select value={verifyStatus || undefined} onChange={v => setVerifyStatus(v || '')} placeholder="全部状态" style={{ width: 110 }} allowClear options={[{ value: 'active', label: '在职' }, { value: 'resigned', label: '离职' }]} />
              <Checkbox checked={verifyOnlyMissing} onChange={e => setVerifyOnlyMissing(e.target.checked)}>仅显示缺失人员</Checkbox>
            </Space>
          </Col>
        </Row>
        <Button type="primary" icon={<SearchOutlined />} loading={verifyLoading} onClick={() => loadVerify(1)}>开始核对</Button>
      </Card>

      {verifyTotal > 0 && (
        <Alert
          style={{ marginBottom: 16 }}
          type={verifyMissingTotal > 0 ? 'warning' : 'success'}
          showIcon
          message={verifyOnlyMissing
            ? `共有 ${verifyTotal} 人信息不完整，请及时完善`
            : `核对范围内共 ${verifyTotal} 人，其中 ${verifyMissingTotal} 人信息不完整`}
        />
      )}

      <Card title="核对结果">
        <Table
          rowKey="employee_id"
          size="middle"
          loading={verifyLoading}
          columns={verifyColumns}
          dataSource={verifyData}
          pagination={{
            current: verifyPage,
            pageSize: 20,
            total: verifyTotal,
            showSizeChanger: false,
            onChange: (p) => loadVerify(p),
          }}
          locale={{ emptyText: verifyTotal > 0 ? '当前条件下暂无信息不完整的人员' : '请选择筛选条件后点击「开始核对」' }}
        />
      </Card>
    </div>
  );

  // [修复 2026-09-01] 新增系统日志 Tab
  const sysLogTab = canViewAudit ? (
    <div>
      <Card title={<><span style={{ marginRight: 8 }}>📋</span>系统日志</>} style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
          {/* [调整 2026-09-19] 按系统日志规范补充说明：级别口径、脱敏与留痕约定，
              让查看者能正确理解各等级含义，并知晓导出/清理会被审计 */}
          查看操作日志、系统日志、错误日志。支持按时间范围、类别、级别、关键字筛选。
          <br />
          级别口径：<Text strong>INFO</Text>＝关键业务动作；<Text strong>WARN</Text>＝已可预知的异常分支（入参错误、旁路失败等）；<Text strong>ERROR</Text>＝需立即处理的严重故障。
          日志中的口令、令牌等敏感信息已统一脱敏；导出与清理操作本身也会记入审计。
        </Text>
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          <Col xs={24} sm={6}>
            <Select value={sysLogCategory || undefined} onChange={v => setSysLogCategory(v || '')} placeholder="全部类别" style={{ width: '100%' }} allowClear
              options={[{ value: 'operation', label: '操作日志' }, { value: 'system', label: '系统日志' }, { value: 'error', label: '错误日志' }]} />
          </Col>
          <Col xs={24} sm={4}>
            <Select value={sysLogLevel || undefined} onChange={v => setSysLogLevel(v || '')} placeholder="全部级别" style={{ width: '100%' }} allowClear
              options={[{ value: 'INFO', label: '信息' }, { value: 'WARN', label: '警告' }, { value: 'ERROR', label: '错误' }]} />
          </Col>
          <Col xs={24} sm={6}>
            {/* [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警 */}
            <Input id="syslog-search" placeholder="搜索关键字" value={sysLogKeyword} onChange={e => setSysLogKeyword(e.target.value)} allowClear />
          </Col>
          <Col xs={24} sm={8}>
            <Space>
              <DatePicker placeholder="开始日期" onChange={d => setSysLogStartDate(d ? d.format('YYYY-MM-DD') : null)} />
              <DatePicker placeholder="结束日期" onChange={d => setSysLogEndDate(d ? d.format('YYYY-MM-DD') : null)} />
            </Space>
          </Col>
        </Row>
        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<SearchOutlined />} loading={sysLogLoading} onClick={() => loadSysLogs(1)}>查询</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportSysLogs}>导出 Excel</Button>
        </Space>
        <div style={{ marginBottom: 12 }}>
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>自动清理：</Text>
            <Select value={sysLogCleanupDays} onChange={setSysLogCleanupDays} style={{ width: 120 }}
              options={[{ value: 30, label: '保留30天' }, { value: 90, label: '保留90天' }, { value: 180, label: '保留180天' }, { value: 365, label: '保留365天' }]} />
            <Button danger size="small" onClick={handleCleanupSysLogs}>清理过期日志</Button>
          </Space>
        </div>
      </Card>
      <Card title="日志列表">
        <Table rowKey="id" size="small" loading={sysLogLoading} columns={sysLogColumns} dataSource={sysLogData}
          pagination={{ current: sysLogPage, pageSize: 20, total: sysLogTotal, showSizeChanger: false, showTotal: t => `共 ${t} 条`, onChange: p => loadSysLogs(p) }}
          locale={{ emptyText: '暂无日志数据，请点击查询' }} />
      </Card>
    </div>
  ) : null;

  return (
    <PageContainer maxWidth={960}>
      <PageHeader title="数据管理" />
      {feedback && <Alert type={feedback.type === 'success' ? 'success' : 'error'} message={feedback.msg} closable showIcon style={{ marginBottom: 16 }} />}
      <Tabs
        defaultActiveKey="export"
        items={[
          { key: 'export', label: '人员导出', children: exportTab },
          { key: 'import', label: '人员导入', children: importTab },
          // [修复 2026-09-03] 新增「标识导出」Tab，将原标识数据导出功能整合到数据管理中
          { key: 'signage-export', label: '标识导出', children: <SignageExport /> },
          // [修复 2026-09-01] 新增「数据核对」Tab
          { key: 'verify', label: '数据核对', children: verifyTab },
          { key: 'backup', label: '备份恢复', children: backupTab },
          // [修复 2026-09-01] 新增「系统日志」Tab（仅 system.audit 权限可见）
          ...(canViewAudit ? [{ key: 'syslog', label: '系统日志', children: sysLogTab }] : []),
        ]}
        onChange={() => { refreshBackups(); refreshPackages(); }}
      />

      {/* [修复] 上传恢复二次密码确认弹窗：输入登录密码后调用恢复接口 */}
      <Modal
        title="恢复数据库 - 二次确认"
        open={restoreModalOpen}
        okText="确认恢复"
        okType="danger"
        confirmLoading={restoreSubmitting}
        onCancel={() => setRestoreModalOpen(false)}
        onOk={async () => {
          if (!pendingRestoreFile) return;
          if (!restorePassword) {
            show('error', '请输入登录密码进行二次确认');
            return;
          }
          setRestoreSubmitting(true);
          setRestoreProgress(0);
          try {
            await uploadRestoreBackup(pendingRestoreFile, restorePassword, (p) => setRestoreProgress(p));
            show('success', '恢复成功');
            setRestoreModalOpen(false);
          } catch (err: any) {
            show('error', err?.response?.data?.detail || '恢复失败');
          } finally {
            setRestoreSubmitting(false);
            setRestoreProgress(0);
          }
        }}
      >
        <Text type="danger" style={{ display: 'block', marginBottom: 12 }}>
          将用 {pendingRestoreFile?.name} 覆盖当前数据库，此操作不可撤销！
        </Text>
        <Input.Password
          // [修复 2026-09-05] 补充 id/name/autocomplete：消除「表单元素缺少 id 或 name」告警并支持密码管理器
          id="restore-password"
          name="restorePassword"
          autoComplete="current-password"
          placeholder="请输入当前登录密码"
          autoFocus
          value={restorePassword}
          disabled={restoreSubmitting}
          onChange={e => setRestorePassword(e.target.value)}
          onPressEnter={() => {
            // 回车直接触发确认恢复（复用 onOk 逻辑）
            if (restorePassword && pendingRestoreFile) {
              const okBtn = document.querySelector<HTMLButtonElement>('.ant-modal-footer .ant-btn-primary');
              okBtn?.click();
            }
          }}
        />
        {restoreSubmitting && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {restoreProgress > 0 && restoreProgress < 100 ? `正在上传：${restoreProgress}%` : '正在上传并写入数据库，请勿关闭窗口…'}
            </Text>
            <Progress percent={restoreProgress} size="small" status="active" style={{ marginTop: 4 }} />
          </div>
        )}
      </Modal>
    </PageContainer>
  );
};

export default DataManage;
