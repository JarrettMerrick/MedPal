// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 人员详情页（信息展示 + 照片/卡片操作 + 修改记录）。
 * [改进] 手写 div → Card/Tag/Descriptions/Modal.confirm
 */

import React, { useEffect, useState, useRef } from 'react';
import { downloadBlob } from '../../utils/fileUtils';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { Card, Descriptions, Tag, Button, Spin, Row, Col, Typography, Space, App, Flex, theme, Divider, Empty, Input } from 'antd';
import { EditOutlined, DeleteOutlined, UserDeleteOutlined, UserAddOutlined, DownloadOutlined, CheckOutlined, CloseOutlined, EyeOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import { getStaff, deleteStaff, updateStaffStatus } from '../../api/staff';
import { getCards, confirmCard, rejectCard } from '../../api/staff-cards';
import { getOriginalUrl, getOriginalPreferredCandidates } from '../../utils/imageUtils';
import SafeImage, { type SafeImageRef } from '../../components/SafeImage';
import type { Staff } from '../../types/staff';
import type { StaffCard } from '../../types/staff-card';
import { parseExpertiseParagraphs } from '../../utils/expertiseParagraphs';
// [修复 2026-09-02] P4: 导入统一错误处理函数
import { getErrorMessage } from '../../utils/format';
import { WORK_TYPE_LABELS, WORK_TYPE_COLOR } from '../../types/staff';
// [调整 2026-09-15] 新增导入 PERM_CARD_UPLOAD：工卡「确认/拒绝」由仅依赖后端 can_confirm 改为前端显式权限判定
// [调整 2026-09-15] 新增导入 PERM_STAFF_VIEW / PERM_STAFF_VIEW_HISTORY：修改历史按钮与后端接口权限保持一致
import { hasPermission, PERM_STAFF_EDIT, PERM_STAFF_DELETE, PERM_STAFF_STATUS, PERM_CARD_UPLOAD, PERM_STAFF_VIEW, PERM_STAFF_VIEW_HISTORY } from '../../utils/permissions';
// [新增 2026-09-15] 修改历史查询按钮：查看最近三次修改的字段级前后对比
import ModificationHistoryButton from '../../components/ModificationHistoryButton';
// [新增 2026-09-11] 人员信息变更审核：详情页显著位置提示「XX 未审核」+ 就地追认/驳回
import { listStaffChangesByStaff, type StaffChangeItem } from '../../api/staffChanges';
import StaffChangeNotice from '../../components/StaffChangeNotice';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';

const { Text, Title } = Typography;
const { useToken } = theme;

/**
 * 照片显示尺寸常量：
 * - 形象照固定 200×260 竖版（比例约 1:1.3），贴合人体证件照比例；
 * - 工卡照高度与形象照一致（260px），宽度按原始比例等比缩放。
 */
const PORTRAIT_PHOTO_W = 200; // 形象照显示宽度
const PORTRAIT_PHOTO_H = 260; // 形象照显示高度（工卡照高度与此对齐）
const CARD_BOX_MIN_W = 150;   // 工卡照最窄宽度（超窄竖图封底，避免过窄难看）
const CARD_BOX_MAX_W = 400;   // 工卡照最宽宽度（超宽横图封顶，避免挤压布局）

// [修复 2026-09-02] P2: 提取高频内联 style 为常量
const STYLES = {
  loading: { textAlign: 'center' as const, padding: 80 } as React.CSSProperties,
  card: { marginBottom: 16 } as React.CSSProperties,
  sectionTitle: { marginTop: 0, marginBottom: 8 } as React.CSSProperties,
  blockText: { display: 'block' as const, marginBottom: 8 } as React.CSSProperties,
  photoContainer: { display: 'flex' as const, flexDirection: 'column' as const, alignItems: 'center', gap: 4 } as React.CSSProperties,
  photoWrapper: { position: 'relative' as const } as React.CSSProperties,
  photoOverlay: { position: 'absolute' as const, inset: 0, background: 'rgba(0,0,0,0.4)', borderRadius: 4, display: 'flex' as const, alignItems: 'center', justifyContent: 'center', gap: 8, opacity: 0 } as React.CSSProperties,
  photoLabel: { fontSize: 12 } as React.CSSProperties,
  preWrap: { whiteSpace: 'pre-wrap' as const, display: 'block' as const, lineHeight: 1.8 } as React.CSSProperties,
  preWrapSimple: { whiteSpace: 'pre-wrap' as const } as React.CSSProperties,
};

/**
 * [改进] 计算工卡照片的显示框尺寸：高度固定与形象照一致（260px），
 * 宽度按图片原始比例等比缩放，并限幅在 [CARD_BOX_MIN_W, CARD_BOX_MAX_W]。
 * 图片本身 objectFit: contain，限幅只影响留白，不会裁切图片。
 */
const computeCardBox = (w: number, h: number): { width: number; height: number } => {
  const ratio = w / h;
  const width = Math.min(CARD_BOX_MAX_W, Math.max(CARD_BOX_MIN_W, Math.round(PORTRAIT_PHOTO_H * ratio)));
  return { width, height: PORTRAIT_PHOTO_H };
};

const StaffDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const { message, modal } = App.useApp();
  const { token } = useToken();

  const [staff, setStaff] = useState<Staff | null>(null);
  const [loading, setLoading] = useState(true);
  const [cards, setCards] = useState<StaffCard[]>([]);
  // [新增 2026-09-11] 待审核变更（立即生效 + 追认审核）：显著位置提示 + 就地审核
  const [pendingChanges, setPendingChanges] = useState<StaffChangeItem[]>([]);
  // [改进] 卡片照片原始尺寸缓存（onLoad 后按实际比例自适应显示框）
  const [cardSizes, setCardSizes] = useState<Record<number, { w: number; h: number }>>({});
  // 每张卡片的 SafeImage 实例 ref，用于触发大图预览
  const cardImageRefs = useRef<Record<number, SafeImageRef | null>>({});
  // [改进] 形象照（正面/侧面）SafeImage 实例 ref，用于触发大图预览
  const frontImageRef = useRef<SafeImageRef | null>(null);
  const sideImageRef = useRef<SafeImageRef | null>(null);

  const isSelf = staff && staff.employee_id === user?.employee_id;
  const canEdit = hasPermission(user, PERM_STAFF_EDIT) || isSelf;
  const canDelete = hasPermission(user, PERM_STAFF_DELETE);
  const canChangeStatus = hasPermission(user, PERM_STAFF_STATUS);
  // [新增 2026-09-15] 工卡「确认/拒绝」显式权限判定（与后端 _can_confirm_card 语义对齐）：
  // 1) 员工本人可确认/拒绝自己的工卡；
  // 2) 持有 card.upload（工卡上传）权限者，可确认/拒绝管辖范围内人员的工卡。
  // 说明：管辖范围（科室作用域）前端无法完全复刻，故仍与后端返回的 card.can_confirm 取交集，
  // 形成「前端显式权限 + 后端权威判定」双重门禁，避免无权限用户看到可操作的按钮。
  const canConfirmCard = !!isSelf || hasPermission(user, PERM_CARD_UPLOAD);
  // [调整 2026-09-15] 修改历史查询入口的显隐：与后端 /api/audit/history 校验一致——
  // 需 staff.view + staff.view_history（「修改历史」独立权限，默认仅超级管理员拥有），
  // 避免无权限用户看到按钮、点击后报 403
  const canViewHistory = hasPermission(user, PERM_STAFF_VIEW) && hasPermission(user, PERM_STAFF_VIEW_HISTORY);

  // [改进] 获取来源页面URL，用于返回按钮恢复原始状态
  const returnTo = (location.state as any)?.returnTo as string | undefined;

  // [新增 2026-09-11] 待审变更加载（审核完成后重新拉取，回滚会改动主表数据）
  const loadPending = React.useCallback(() => {
    if (!id) return;
    listStaffChangesByStaff(id)
      .then((r) => setPendingChanges(r.items))
      .catch(() => setPendingChanges([]));
  }, [id]);

  useEffect(() => {
    if (id) {
      getStaff(id).then((data) => { setStaff(data); setLoading(false); }).catch(() => navigate(returnTo || '/staff'));
      getCards({ entity_id: id, page: 1, page_size: 100 }).then((data) => {
        setCards(data.items.filter((c) => c.status !== 'rejected'));
      }).catch(() => {});
      loadPending();
    }
  }, [id, navigate, returnTo, loadPending]);

  const handleDelete = () => {
    if (!staff) return;
    modal.confirm({
      title: `确定要删除 ${staff.name}（${staff.employee_id}）吗？`,
      content: '此操作不可恢复！',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => { try { await deleteStaff(staff.employee_id); navigate(returnTo || '/staff'); } catch (err) { message.error(getErrorMessage(err, '删除失败')); } },
    });
  };

  /**
   * 切换在职/离职状态
   * [调整 2026-09-11] 标记离职时补充「离职原因」（可选，写入 staff.resign_reason），
   * 并明确告知：登录账号会被停用，且会通过站内信通知超管与相关科室管理员。
   */
  const handleToggleStatus = () => {
    if (!staff) return;
    if (staff.status === 'resigned') {
      modal.confirm({
        title: `确定要将 ${staff.name}（${staff.employee_id}）恢复在职吗？`,
        content: '恢复后将清空其离职记录（离职时间/原因），登录账号同步恢复启用。',
        okText: '确认恢复', cancelText: '取消',
        onOk: async () => {
          try {
            await updateStaffStatus(staff.employee_id, 'active');
            setStaff({ ...staff, status: 'active', resigned_at: null, resign_reason: null });
            message.success('已恢复在职');
          } catch (err) { message.error(getErrorMessage(err, '操作失败')); }
        },
      });
      return;
    }

    let reason = '';
    modal.confirm({
      title: `确定要将 ${staff.name}（${staff.employee_id}）标记离职吗？`,
      okText: '确认离职', okType: 'danger', cancelText: '取消',
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>
            标记后其登录账号将<strong>立即停用</strong>，并通过站内信通知超级管理员与相关科室管理员。
          </p>
          <Input
            placeholder="离职原因（可选，便于后续核查）"
            maxLength={200}
            onChange={(e) => { reason = e.target.value; }}
          />
        </div>
      ),
      onOk: async () => {
        try {
          const trimmed = reason.trim();
          await updateStaffStatus(staff.employee_id, 'resigned', trimmed || undefined);
          setStaff({
            ...staff, status: 'resigned',
            resigned_at: new Date().toISOString(),
            resign_reason: trimmed || null,
          });
          message.success('已标记离职');
        } catch (err) { message.error(getErrorMessage(err, '操作失败')); }
      },
    });
  };

  const handleConfirmCard = async (cardId: number) => {
    try { await confirmCard(cardId); setCards((p) => p.map((c) => c.id === cardId ? { ...c, status: 'confirmed' } : c)); } catch (err) { message.error(getErrorMessage(err, '确认失败')); }
  };

  const handleRejectCard = (cardId: number) => {
    // [保留] window.prompt 用于拒绝原因输入（Ant Design 无直接替代）
    const reason = window.prompt('请输入拒绝原因（可选）：');
    if (reason === null) return;
    rejectCard(cardId, reason || undefined).then(() => {
      setCards((p) => p.filter((c) => c.id !== cardId));
    }).catch((err) => message.error(getErrorMessage(err, '拒绝失败')));
  };

  // [改进] 下载文件名格式：工号_类型（front/side/card），与批量导入命名规则一致，后缀取真实内容类型。
  const downloadImage = async (path: string, typeLabel: string) => {
    try {
      const employeeId = staff?.employee_id || 'unknown';
      const realExt = path.includes('.') ? path.slice(path.lastIndexOf('.')) : '.jpg';
      let finalName = `${employeeId}_${typeLabel}${realExt}`;
      // [改进] 优先下载原始照片（orig_ 副本，多扩展名候选逐级探测）；旧数据无 orig_ 时回退正式图
      let url = getOriginalUrl(path) || '';
      for (const cand of getOriginalPreferredCandidates(path)) {
        try {
          const probe = await fetch(cand, { method: 'HEAD' });
          if (probe.ok) {
            url = cand;
            break;
          }
        } catch { /* ignore */ }
      }
      const resp = await fetch(url);
      const blob = await resp.blob();
      // [改进] 下载扩展名以真实内容为准（原图可能是 PNG/WebP，而非正式图的 .jpg）
      const mimeExt: Record<string, string> = { 'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp' };
      finalName = `${employeeId}_${typeLabel}${mimeExt[blob.type] || realExt}`;
      // [修正 2026-09-22] 改用公共 downloadBlob：原实现缺 appendChild
      // （Firefox 下 click() 不触发下载），且 revoke 紧跟 click 之后。
      downloadBlob(blob, finalName);
    } catch { /* silent */ }
  };

  if (loading) return <div style={STYLES.loading}><Spin size="large" /></div>;
  if (!staff) return null;

  const showAdvanced = staff.work_type === 'doctor' || staff.work_type === 'technician';

  // [改进/1.1] 渲染单个专业能力字段：解析为分段落并清晰分隔（标题层级 + 间距 token + 分割线）
  const renderExpertiseField = (label: string, raw: string | null | undefined) => {
    const paragraphs = parseExpertiseParagraphs(raw);
    if (paragraphs.length === 0) return null;
    return (
      <div style={{ marginBottom: token.marginLG }}>
        <Title level={5} style={{ marginTop: 0, marginBottom: token.marginSM, color: token.colorPrimary }}>{label}</Title>
        <Flex vertical gap={token.marginMD}>
          {paragraphs.map((p) => (
            <div key={p.sort_order}>
              {p.sort_order > 0 && <Divider style={{ margin: `${token.marginSM}px 0` }} />}
              {p.title && (
                <Text strong style={{ display: 'block', marginBottom: token.marginXS, color: token.colorText }}>
                  {p.title}
                </Text>
              )}
              <Text style={{ whiteSpace: 'pre-wrap', display: 'block', lineHeight: 1.8 }}>{p.content}</Text>
            </div>
          ))}
        </Flex>
      </div>
    );
  };

  return (
    <PageContainer maxWidth={960}>
      {/* Header */}
      <PageHeader
        title={staff.name}
        onBack={() => navigate(returnTo || '/staff')}
        extra={(
          <Space>
            {/* [新增 2026-09-15] 修改历史查询：置于「编辑」左侧，展示最近三次修改的字段级前后对比 */}
            {canViewHistory && (
              <ModificationHistoryButton
                entityType="staff"
                entityId={staff.employee_id}
                entityName={staff.name}
              />
            )}
            {canEdit && <Button icon={<EditOutlined />} onClick={() => navigate(`/staff/edit/${staff.employee_id}`, { state: { returnTo } })}>编辑</Button>}
            {canChangeStatus && (
              <Button
                icon={staff.status === 'active' ? <UserDeleteOutlined /> : <UserAddOutlined />}
                danger={staff.status === 'active'}
                onClick={handleToggleStatus}
              >
                {staff.status === 'active' ? '标记离职' : '恢复在职'}
              </Button>
            )}
            {canDelete && <Button danger icon={<DeleteOutlined />} onClick={handleDelete}>删除</Button>}
          </Space>
        )}
      />

      {/* [新增 2026-09-11] 显著位置提示「XX 未审核」；审核人可直接就地追认/驳回 */}
      <StaffChangeNotice
        changes={pendingChanges}
        onReviewed={() => {
          loadPending();
          if (id) getStaff(id).then(setStaff).catch(() => {});
        }}
      />

      {/* 基本信息 */}
      {/* [改进] 固定 8 项，lg 4 列×2 行 / sm 2 列×4 行 / xs 1 列×8 行，任意断点下都是满阵；
          学历不再条件插入（无值显示 '-'），避免字段缺失导致列错位；bordered 强化网格对齐 */}
      <Card title="基本信息" style={STYLES.card}>
        <Descriptions column={{ xs: 1, sm: 2, lg: 4 }} size="small" bordered>
          <Descriptions.Item label="工号"><Text strong>{staff.employee_id}</Text></Descriptions.Item>
          <Descriptions.Item label="姓名">{staff.name}</Descriptions.Item>
          <Descriptions.Item label="工种">
            <Tag color={WORK_TYPE_COLOR[staff.work_type] || 'default'}>{WORK_TYPE_LABELS[staff.work_type] || staff.work_type}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="所属部门">{staff.department || '-'}</Descriptions.Item>
          <Descriptions.Item label="职称">{staff.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="职务">{staff.position || '-'}</Descriptions.Item>
          <Descriptions.Item label="学历">{staff.education || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={staff.status === 'active' ? 'green' : 'default'}>{staff.status === 'active' ? '在职' : '离职'}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 照片资料：形象照（左栏）+ 工作卡片（右栏）左右排列。
          [改进] 始终渲染两栏；未上传时 SafeImage 传 emptyText 显示"暂未上传，请上传！"占位框，
          已上传但文件丢失沿用 SafeImage 现有"文件已丢失/请重新上传"占位（规则同前）。 */}
      <Card title="照片资料" style={STYLES.card}>
        <Row gutter={[token.marginLG, token.marginMD]} align="top">
          {/* —— 左栏：形象照（正面/侧面始终渲染，未上传显示占位框） —— */}
          <Col flex="0 0 auto">
            <Text strong style={STYLES.blockText}>形象照</Text>
            <Flex gap={token.marginLG} align="flex-start" wrap="wrap">
              {/* 正面形象照：200×260 竖版（比例约 1:1.3） */}
              <div className="staff-detail-photo" style={STYLES.photoContainer}>
                <div className="staff-detail-image" style={STYLES.photoWrapper}>
                  <SafeImage
                    ref={frontImageRef}
                    src={staff.front_photo}
                    emptyText="暂未上传，请上传！"
                    alt="正面形象照"
                    style={{ width: PORTRAIT_PHOTO_W, height: PORTRAIT_PHOTO_H, objectFit: 'cover', borderRadius: token.borderRadius }}
                  />
                  {staff.front_photo && (
                    <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)', borderRadius: token.borderRadius, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: token.marginSM, opacity: 0 }}>
                      <Button size="small" ghost icon={<EyeOutlined />} onClick={() => frontImageRef.current?.preview()}>预览</Button>
                      <Button size="small" ghost icon={<DownloadOutlined />} onClick={() => downloadImage(staff.front_photo!, 'front')}>下载</Button>
                    </div>
                  )}
                </div>
                <Text type="secondary" style={STYLES.photoLabel}>正面</Text>
              </div>
              {/* 侧面形象照：200×260 竖版 */}
              <div className="staff-detail-photo" style={STYLES.photoContainer}>
                <div className="staff-detail-image" style={STYLES.photoWrapper}>
                  <SafeImage
                    ref={sideImageRef}
                    src={staff.side_photo}
                    emptyText="暂未上传，请上传！"
                    alt="侧面形象照"
                    style={{ width: PORTRAIT_PHOTO_W, height: PORTRAIT_PHOTO_H, objectFit: 'cover', borderRadius: token.borderRadius }}
                  />
                  {staff.side_photo && (
                    <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)', borderRadius: token.borderRadius, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: token.marginSM, opacity: 0 }}>
                      <Button size="small" ghost icon={<EyeOutlined />} onClick={() => sideImageRef.current?.preview()}>预览</Button>
                      <Button size="small" ghost icon={<DownloadOutlined />} onClick={() => downloadImage(staff.side_photo!, 'side')}>下载</Button>
                    </div>
                  )}
                </div>
                <Text type="secondary" style={STYLES.photoLabel}>侧面</Text>
              </div>
            </Flex>
          </Col>

          {/* —— 右栏：工作卡片（始终渲染，未上传卡片照片显示占位框） —— */}
          <Col flex="1 1 0" style={{ minWidth: 280 }}>
            <Text strong style={STYLES.blockText}>工作卡片</Text>
            {cards.length > 0 ? (
              <Flex gap={token.marginLG} align="flex-start" wrap="wrap">
                {cards.map((card) => {
                  // [改进] 显示框高度固定与形象照一致（260px），宽度按图片实际比例自适应；
                  // 加载完成前使用竖版占位，onLoad 读取 naturalWidth/Height 后更新。
                  const size = cardSizes[card.id];
                  const box = size ? computeCardBox(size.w, size.h) : { width: PORTRAIT_PHOTO_W, height: PORTRAIT_PHOTO_H };
                  return (
                    <div key={card.id} className="staff-detail-photo" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: token.marginXS }}>
                      <div className="staff-detail-image" style={{ position: 'relative' }}>
                        <SafeImage
                          ref={(el) => { cardImageRefs.current[card.id] = el; }}
                          src={card.card_photo}
                          emptyText="暂未上传，请上传！"
                          alt="工作卡片"
                          onLoad={(e) => {
                            const img = e.target as HTMLImageElement;
                            if (img.naturalWidth && img.naturalHeight) {
                              setCardSizes((prev) => (
                                prev[card.id] && prev[card.id].w === img.naturalWidth && prev[card.id].h === img.naturalHeight
                                  ? prev
                                  : { ...prev, [card.id]: { w: img.naturalWidth, h: img.naturalHeight } }
                              ));
                            }
                          }}
                          style={{
                            width: box.width,
                            height: box.height,
                            objectFit: 'contain',
                            backgroundColor: token.colorFillQuaternary,
                            borderRadius: token.borderRadius,
                            objectPosition: 'center',
                          }}
                        />
                        {card.card_photo && (
                          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)', borderRadius: token.borderRadius, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: token.marginSM, opacity: 0 }}>
                            <Button size="small" ghost icon={<EyeOutlined />} onClick={() => cardImageRefs.current[card.id]?.preview()}>预览</Button>
                            <Button size="small" ghost icon={<DownloadOutlined />} onClick={() => downloadImage(card.card_photo, 'card')}>下载</Button>
                            {/* [调整 2026-09-15] 显式权限判定 canConfirmCard 前置 + 后端 can_confirm（含管辖范围）收敛：
                                无 card.upload 权限且非本人时，确认/拒绝按钮直接不渲染 */}
                            {card.status === 'pending' && canConfirmCard && card.can_confirm && (
                              <>
                                <Button size="small" ghost icon={<CheckOutlined />} onClick={() => handleConfirmCard(card.id)}>确认</Button>
                                <Button size="small" danger ghost icon={<CloseOutlined />} onClick={() => handleRejectCard(card.id)}>拒绝</Button>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                      <Space size={token.marginXS}>
                        <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>卡片照片</Text>
                        <Tag color={card.status === 'confirmed' ? 'green' : card.status === 'pending' ? 'gold' : 'default'}>
                          {card.status === 'confirmed' ? '已确认' : card.status === 'pending' ? '待确认' : '已拒绝'}
                        </Tag>
                      </Space>
                    </div>
                  );
                })}
              </Flex>
            ) : (
              // [改进] 无卡片记录时的空态占位
              <div className="staff-detail-photo" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: token.marginXS }}>
                <div className="staff-detail-image">
                  <SafeImage
                    src={null}
                    emptyText="暂未上传，请上传！"
                    alt="工作卡片"
                    style={{ width: PORTRAIT_PHOTO_W, height: PORTRAIT_PHOTO_H, objectFit: 'contain', backgroundColor: token.colorFillQuaternary, borderRadius: token.borderRadius, objectPosition: 'center' }}
                  />
                </div>
                <Space size={token.marginXS}>
                  <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>卡片照片</Text>
                  <Tag color="default">待上传</Tag>
                </Space>
              </div>
            )}
          </Col>
        </Row>
      </Card>

      {/* 专业能力 */}
      {showAdvanced && (
        <Card title="专业能力" style={STYLES.card}>
          {/* 专业擅长（简）：单段纯文本 + 标题右侧固定提醒 */}
          {staff.expertise_short && (
            <div style={{ marginBottom: token.marginLG }}>
              <Flex justify="space-between" align="center" wrap="wrap" gap={token.marginSM} style={{ marginBottom: token.marginXS }}>
                <Title level={5} style={{ ...STYLES.sectionTitle, color: token.colorPrimary }}>专业擅长（简）</Title>
                <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                  100 字以内，用于文字排版不能显示太多的地方
                </Text>
              </Flex>
              <Text style={STYLES.preWrapSimple}>{staff.expertise_short}</Text>
            </div>
          )}

          {/* 专业擅长（标准）/ 社会任职 / 获得荣誉：支持分段落（标题+内容+排序） */}
          {renderExpertiseField('专业擅长', staff.expertise_standard)}
          {renderExpertiseField('社会任职', staff.social_appointments)}
          {renderExpertiseField('获得荣誉', staff.honors)}

          {/* 全部为空时占位 */}
          {!staff.expertise_short && !staff.expertise_standard && !staff.social_appointments && !staff.honors && (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无专业能力信息" />
          )}
        </Card>
      )}

      {/* 备注 */}
      {staff.remarks && (
        <Card title="备注" style={STYLES.card}><Text style={STYLES.preWrapSimple}>{staff.remarks}</Text></Card>
      )}

      {/* [调整 2026-09-11] 原「修改记录」区块随信息修改功能下线删除；
          人员信息的修改提醒现通过站内信推送给超管与相关科室管理员 */}

      <style>{`
        .staff-detail-image:hover > button,
        .staff-detail-image:hover > div { opacity: 1 !important; }
      `}</style>
    </PageContainer>
  );
};

export default StaffDetail;
