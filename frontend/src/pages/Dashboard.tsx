// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 工作台仪表盘页面，登录后的默认首页。
 * 负责：
 * 1. 统计卡片（员工总数、个人信息）
 * 2. 公告栏（富文本渲染 + 权限控制编辑）
 * 3. 30 秒轮詢公告更新 + 页面可见性刷新
 * 
 * 改造说明（v1.1.0）：
 * - [改进] 手写 grid + card → Row/Col 栅格 + Card + Statistic 组件
 * - [改进] 手写按钮 → Button 组件
 * - [改进] 手写公告栏 → Card + Alert 样式优化
 * - RichTextEditor / DOMPurify 保留不变
 * - 业务逻辑不变：统计数据加载、公告轮询、权限判断
 */

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Row, Col, Card, Statistic, Button, Typography, message, Spin, theme, Flex } from 'antd';
import { TeamOutlined, UserOutlined, MobileOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import { getStaffList, getStaff } from '../api/staff';
import { getSystemConfig, updateSystemConfig } from '../api/system-config';
import RichTextEditor from '../components/RichTextEditor';
// [修复 2026-09-09] 统一富文本渲染容器：公告展示与编辑器预览、制度详情口径一致
import RichTextContent from '../components/RichTextContent';
// [新增 2026-09-08] 工作台新增标识巡检快捷卡片（权限与巡检页路由守卫一致）
import { hasPermission, PERM_SYSTEM_CONFIG, PERM_SIGNAGE_INSPECTION } from '../utils/permissions';
// [修复 2026-09-02] P4: 导入统一错误处理函数
import { getErrorMessage } from '../utils/format';
import PageContainer from '../components/PageContainer';
import PageHeader from '../components/PageHeader';
// [新增 2026-09-10] 首页同时展示单位名称与系统名称
import { useBranding } from '../contexts/BrandingContext';

const { Text } = Typography;
const { useToken } = theme;

interface Stats {
  totalStaff: number;
}

/**
 * [调整 2026-09-10] 公告栏占位文案。
 * 原先在「未配置公告」或「读取失败」时显示一段欢迎语，容易被误认为是真实公告；
 * 现统一显示「暂无公告」，空即是空。
 */
const EMPTY_NOTICE_TEXT = '暂无公告';

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const branding = useBranding(); // [新增 2026-09-10] 品牌信息
  const { token } = useToken();
  const [stats, setStats] = useState<Stats>({ totalStaff: 0 });
  const [statsLoading, setStatsLoading] = useState(true);
  const [syncNotice, setSyncNotice] = useState<string>('');
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [profilePath, setProfilePath] = useState<string>('/profile');

  useEffect(() => {
    // 加载统计数据
    getStaffList({ page: 1, page_size: 1 })
      .then((res) => setStats({ totalStaff: res.total }))
      .finally(() => setStatsLoading(false));

    loadSyncNotice();
    checkProfilePath();

    // 30 秒轮询公告
    const noticeInterval = setInterval(loadSyncNotice, 30000);

    // 页面可见性变化时刷新
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') loadSyncNotice();
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      clearInterval(noticeInterval);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []);

  const loadSyncNotice = async () => {
    try {
      const config = await getSystemConfig('data_sync_notice');
      setSyncNotice(config.config_value || '');
    } catch {
      // [调整 2026-09-10] 读取失败时同样显示占位文案（原先回退到一段欢迎语，易被误认为真实公告）
      setSyncNotice(EMPTY_NOTICE_TEXT);
    }
  };

  const checkProfilePath = async () => {
    if (!user?.employee_id) return;
    // [改进] 优先使用后端返回的 has_staff_record 判断是否有员工记录，避免对无员工记录的
    // 账号（如纯管理员 admin）发起 getStaff 探测请求造成无害 404 噪音。
    // 仅当后端未返回该字段（has_staff_record === undefined，旧后端）时，回退到原探测逻辑。
    if (user.has_staff_record !== undefined) {
      setProfilePath(user.has_staff_record ? `/staff/view/${user.employee_id}` : '/profile');
      return;
    }
    try {
      await getStaff(user.employee_id);
      setProfilePath(`/staff/view/${user.employee_id}`);
    } catch {
      setProfilePath('/profile');
    }
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      await updateSystemConfig('data_sync_notice', editValue);
      setSyncNotice(editValue);
      setIsEditing(false);
      message.success('保存成功'); // [改进] 使用 message.success 替代 alert
    } catch (error) {
      message.error('保存失败: ' + getErrorMessage(error, '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  const canEditNotice = hasPermission(user, PERM_SYSTEM_CONFIG);

  /** 获取角色中文名称 */
  const getRoleName = (role: string) => {
    const roleMap: Record<string, string> = {
      admin_manager: '超级管理员',
      dept_manager: '科室管理员',
      employee: '员工',
    };
    return roleMap[role] || role;
  };

  return (
    <PageContainer>
      {/* 欢迎区 */}
      <PageHeader title="工作台" description={`${branding.orgNameCn} · ${branding.systemName}`} />

      {/*
        统计卡片（[改进 2026-09-10]）
        - 调整到公告栏**上方**，进入工作台先看到关键数据与快捷入口；
        - 三张卡片等高：Col 设为 flex 容器、Card 用 flex:1 撑满，
          使高度统一由最高的一张决定，不再出现参差不齐；
        - 数值字号统一为 fontSizeHeading3（原先"员工总数"用默认 24px，明显小于另两张）。
      */}
      <Row gutter={[token.marginMD, token.marginMD]} style={{ marginBottom: token.marginLG }}>
        {/* 员工总数 */}
        <Col xs={24} md={12} lg={8} style={{ display: 'flex' }}>
          <Card
            hoverable
            onClick={() => navigate('/staff')}
            style={{ cursor: 'pointer', flex: 1 }}
          >
            {statsLoading ? (
              <Flex justify="center" style={{ padding: token.paddingMD }}><Spin /></Flex>
            ) : (
              <Statistic
                title="员工总数"
                value={stats.totalStaff}
                prefix={<TeamOutlined />}
                valueStyle={{ color: token.colorPrimary, fontSize: token.fontSizeHeading3 }}
              />
            )}
          </Card>
        </Col>

        {/* 个人信息 */}
        <Col xs={24} md={12} lg={8} style={{ display: 'flex' }}>
          <Card
            hoverable
            onClick={() => navigate(profilePath)}
            style={{ cursor: 'pointer', flex: 1 }}
          >
            <Statistic
              title="个人信息"
              value={user?.name || '--'}
              prefix={<UserOutlined />}
              valueStyle={{ color: token.purple6, fontSize: token.fontSizeHeading3 }}
            />
            {user?.employee_id && (
              <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXS }}>
                {user.employee_id} · {getRoleName(user.role)}
              </Text>
            )}
          </Card>
        </Col>

        {/* [新增 2026-09-08] 标识巡检快捷卡片：点击进入标识巡检页；仅对拥有巡检权限的用户显示 */}
        {hasPermission(user, PERM_SIGNAGE_INSPECTION) && (
          <Col xs={24} md={12} lg={8} style={{ display: 'flex' }}>
            <Card
              hoverable
              onClick={() => navigate('/signage-mobile')}
              style={{ cursor: 'pointer', flex: 1 }}
            >
              <Statistic
                title="标识巡检"
                value="快捷进入"
                prefix={<MobileOutlined />}
                valueStyle={{ color: token.colorPrimary, fontSize: token.fontSizeHeading3 }}
              />
              <Text type="secondary" style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXS }}>
                扫码/输入标识编号，提交巡检结果与现场照片
              </Text>
            </Card>
          </Col>
        )}
      </Row>

      {/*
        公告栏（[改进 2026-09-10] 调整到统计卡片**下方**：
        进入工作台优先呈现关键数据与快捷入口，公告作为补充信息置后）
      */}
      <Card style={{ marginBottom: token.marginLG }}>
        {/* 公告栏内容块 */}
        <div
          style={{
            marginTop: token.marginMD,
            padding: `${token.paddingMD}px ${token.paddingLG}px`,
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadiusLG,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <Text strong style={{ fontSize: token.fontSizeLG }}>公告栏</Text>
            {canEditNotice && !isEditing && (
              <Button
                type="link"
                size="small"
                onClick={() => { setEditValue(syncNotice); setIsEditing(true); }}
              >
                编辑
              </Button>
            )}
          </div>
          {isEditing ? (
            <div style={{ marginTop: 8 }}>
              <RichTextEditor
                value={editValue}
                onChange={setEditValue}
                placeholder="输入公告内容..."
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: token.marginXS, marginTop: token.marginSM }}>
                <Button size="small" onClick={() => setIsEditing(false)}>取消</Button>
                <Button
                  type="primary"
                  size="small"
                  loading={loading}
                  onClick={handleSave}
                >
                  保存
                </Button>
              </div>
            </div>
          ) : (
            <RichTextContent
              html={syncNotice || EMPTY_NOTICE_TEXT}
              style={{ fontSize: token.fontSizeSM, lineHeight: 1.6, color: token.colorText, marginTop: 4 }}
            />
          )}
        </div>
      </Card>
    </PageContainer>
  );
};

export default Dashboard;
