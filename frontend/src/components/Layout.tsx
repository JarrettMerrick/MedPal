// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 应用主布局框架，负责：
 * 1. 左侧导航（桌面端折叠侧边栏，移动端抽屉式菜单）
 * 2. 顶部标题栏（用户信息、通知、快捷操作）
 * 3. 内容区域 `<Outlet />` 渲染子路由页面
 * 4. 全局级模态框（修改密码、强制改密、问题反馈）
 * 5. 5 分钟无操作自动退出
 * 6. 通过 LayoutContext 向子组件暴露侧边栏折叠状态
 *
 * 改造说明（v1.1.0 UI 精致化，2026-08-07）：
 * - [改进] 导航按「概览 / 业务 / 系统」分组，提升信息层级
 * - [改进] 侧边栏由深色 #001529 改为浅色轻盈风格，品牌区使用 MedPal_Logo.png
 * - [改进] 选中态浅青胶囊 + 左侧主色竖条（详见 global.css）
 * - [改进] 顶栏/底部/头像等硬编码色值统一收敛到医疗青蓝 token 体系
 * - 业务逻辑不变：空闲退出、强制改密、权限过滤导航、通知组件
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import LayoutContext from '../contexts/LayoutContext';
import { getRoleLabel } from '../utils/roles'; // [改进] getRoleColor 移除此处，改用 getRoleBadgeStyle
// [修复 2026-09-07] 标识菜单门禁改用细粒度权限（标识平面/标识设置两大分类）
import { hasPermission, PERM_REGULATION_VIEW, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_MARKER, PERM_SIGNAGE_ALERT, PERM_SIGNAGE_INSPECTION, PERM_SIGNAGE_REPAIR, PERM_SIGNAGE_FLOORPLAN, PERM_SIGNAGE_CAMPUS, PERM_SIGNAGE_CATEGORY, PERM_SIGNAGE_SUPPLIER, PERM_STAFF_VIEW_RESIGNED, PERM_DATA_EXPORT, PERM_USER_VIEW, PERM_ROLE_VIEW, PERM_SYSTEM_CONFIG, PERM_USER_APPROVE, PERM_MESSAGE_VIEW, PERM_STAFF_APPROVE } from '../utils/permissions';
import useMediaQuery from '../hooks/useMediaQuery'; // [改进] 响应式断点 Hook
import ChangePasswordModal from './ChangePasswordModal';
import NotificationBell from './NotificationBell';
import ChangelogModal from './ChangelogModal'; // [改进] 版本更新记录弹窗
// [调整 2026-09-10] 统一品牌 Logo 组件：显示高度固定、宽度按 Logo 原始比例等比伸缩
import BrandLogo from './BrandLogo';
// [新增 2026-09-10] 全局品牌信息（单位名称 / 已上传 Logo）
import { useBranding } from '../contexts/BrandingContext';

// [改进] Ant Design 组件（全部本地化，内网可用）
import { Layout, Menu, Button, Dropdown, Space, Modal, Typography, Drawer, Avatar, theme } from 'antd';
import type { MenuProps } from 'antd';
import {
  HomeOutlined, TeamOutlined, BankOutlined, FileTextOutlined,
  UserDeleteOutlined, AlertOutlined, DatabaseOutlined, UserOutlined,
  SafetyCertificateOutlined, MenuOutlined, TagsOutlined,
  LogoutOutlined, LockOutlined, MessageOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined,
  ApartmentOutlined, MobileOutlined,
  // [新增 2026-09-09] 标识总览与维修记录菜单图标
  DashboardOutlined, ToolOutlined,
  // [新增 2026-09-10] 系统设置菜单图标
  SettingOutlined,
  // [新增 2026-09-10] 单位设置 / 账号设置 / 信息审核图标
  PictureOutlined, UserSwitchOutlined, AuditOutlined,
} from '@ant-design/icons';
import type { ItemType } from 'antd/es/menu/interface';
import pkg from '../../package.json'; // [改进] 从 package.json 读取版本号，避免硬编码导致发版遗漏（路径需指向 frontend 根目录）

const { Sider, Header: AntHeader, Content } = Layout;
const { Text } = Typography;

// ==================== 常量 ====================

/** [改进] 浅色侧边栏配色（医疗青蓝 token 体系） */
const SIDER = {
  bg: '#FFFFFF',
  border: '#EDF0F3',
  text: '#1F2D3D',
  textSecondary: '#5C6B7A',
  textTertiary: '#8A97A6',
  logoBg: 'linear-gradient(135deg, #0E7F8A, #0A6771)',
} as const;

/** [新增 2026-09-11] 菜单权限：支持单个权限或权限数组（数组 = 任一满足即可显示） */
type NavPermission = string | string[];

/** [改进] 导航配置：按「概览 / 业务 / 系统」分组，icon 使用 @ant-design/icons（内嵌 SVG，不需要外部资源） */
const navGroups: Array<{
  title: string;
  items: Array<{
    path: string;
    // [修复 2026-09-09] 父菜单标签改为链接节点（点击「标识平面」直接进入标识总览）
    label: string | React.ReactNode;
    icon: React.ReactNode;
    permission?: NavPermission;
    children?: Array<{
      path: string;
      label: string;
      icon: React.ReactNode;
      permission?: NavPermission;
    }>;
  }>;
}> = [
  {
    title: '概览',
    items: [
      { path: '/dashboard', label: '工作台', icon: <HomeOutlined /> },
      // [新增 2026-09-11] 站内信：系统通知 + 管理员群发/私发的统一收件箱
      { path: '/messages', label: '站内信', icon: <MessageOutlined />, permission: PERM_MESSAGE_VIEW },
    ],
  },
  {
    title: '业务',
    items: [
      { path: '/staff', label: '人员管理', icon: <TeamOutlined /> },
      { path: '/departments', label: '科室管理', icon: <BankOutlined /> },
      { path: '/regulations', label: '制度管理', icon: <FileTextOutlined />, permission: PERM_REGULATION_VIEW },
      // [修复 2026-09-04] 标识平面菜单，将标识相关菜单项移入子菜单
      // [修复 2026-09-07] 子菜单门禁按细粒度权限拆分（标识管理/标识标记/标识预警/标识巡检）
      {
        path: '/signage-workspace',
        // [修复 2026-09-09] 点击「标识平面」直接跳转到标识总览（同时保留展开子菜单行为）
        label: <Link to="/signage-overview">标识平面</Link>,
        icon: <TagsOutlined />,
        children: [
          { path: '/signage-overview', label: '标识总览', icon: <DashboardOutlined />, permission: PERM_SIGNAGE_VIEW },
          { path: '/signages', label: '标识管理', icon: <TagsOutlined />, permission: PERM_SIGNAGE_VIEW },
          { path: '/signage-floorplan', label: '标识标记', icon: <ApartmentOutlined />, permission: PERM_SIGNAGE_MARKER },
          // [新增 2026-09-09] 维修记录：位于标识标记下方，查看全部标识维修记录并导出
          { path: '/signage-repairs', label: '维修记录', icon: <ToolOutlined />, permission: PERM_SIGNAGE_REPAIR },
          { path: '/signage-alerts', label: '标识预警', icon: <AlertOutlined />, permission: PERM_SIGNAGE_ALERT },
          { path: '/signage-mobile', label: '标识巡检', icon: <MobileOutlined />, permission: PERM_SIGNAGE_INSPECTION },
        ],
      },
      // [调整 2026-09-11] 「员工休息区」更名为「离职人员」（语义更直白：离职档案 + 保留期管理）
      { path: '/staff-rest-area', label: '离职人员', icon: <UserDeleteOutlined />, permission: PERM_STAFF_VIEW_RESIGNED },
      // [调整 2026-09-11] 「信息审核」合并两个 Tab：账号注册审核（user.approve）+
      // 信息变更审核（staff.approve）；具备任一权限即可见（页内按权限只显示对应 Tab）
      {
        path: '/registration-review',
        label: '信息审核',
        icon: <AuditOutlined />,
        permission: [PERM_USER_APPROVE, PERM_STAFF_APPROVE],
      },
    ],
  },
  {
    title: '系统',
    items: [
      // [调整 2026-09-11] 「信息修改」功能整体下线（页面/路由/接口均已删除），
      // 人员/科室等信息修改提醒统一改由「站内信」推送给超管与相关科室管理员
      // [修复 2026-09-07] 标识设置移入系统分组，置于数据管理上方；
      // 父级不再挂单一权限，由子项各自门禁，子项全部无权限时父级自动隐藏
      {
        path: '/signage-settings',
        label: '标识设置',
        icon: <BankOutlined />,
        children: [
          { path: '/campus-management', label: '院区管理', icon: <BankOutlined />, permission: PERM_SIGNAGE_CAMPUS },
          { path: '/signage-plan-settings', label: '平面设置', icon: <ApartmentOutlined />, permission: PERM_SIGNAGE_FLOORPLAN },
          { path: '/signage-categories', label: '标识分类', icon: <TagsOutlined />, permission: PERM_SIGNAGE_CATEGORY },
          { path: '/suppliers', label: '供应商设置', icon: <TeamOutlined />, permission: PERM_SIGNAGE_SUPPLIER },
        ],
      },
      { path: '/data', label: '数据管理', icon: <DatabaseOutlined />, permission: PERM_DATA_EXPORT },
      { path: '/users', label: '用户管理', icon: <UserOutlined />, permission: PERM_USER_VIEW },
      // [调整 2026-09-10] 「系统设置」父级菜单：单位设置 / 账号设置 / 角色管理
      {
        path: '/system-settings-group',
        label: '系统设置',
        icon: <SettingOutlined />,
        children: [
          { path: '/system-settings', label: '单位设置', icon: <PictureOutlined />, permission: PERM_SYSTEM_CONFIG },
          { path: '/account-settings', label: '账号设置', icon: <UserSwitchOutlined />, permission: PERM_SYSTEM_CONFIG },
          // [调整 2026-09-10] 角色管理由顶级项移入「系统设置」父级菜单（路由 /roles 与权限不变）
          { path: '/roles', label: '角色管理', icon: <SafetyCertificateOutlined />, permission: PERM_ROLE_VIEW },
        ],
      },
    ],
  },
];

/** 5 分钟无操作自动退出 */
const IDLE_TIMEOUT = 5 * 60 * 1000;

// ==================== 组件 ====================

const AppLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, logout, isFirstLogin, setUser } = useAuth();
  const branding = useBranding(); // [新增 2026-09-10] 单位 Logo 与单位名称
  const location = useLocation();
  const navigate = useNavigate();
  const { token } = theme.useToken();

  // 响应式状态
  const isMobile = useMediaQuery('(max-width: 991px)'); // [改进] 替代手动 resize 监听
  const [desktopCollapsed, setDesktopCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // 模态框状态
  const [showChangePwd, setShowChangePwd] = useState(false);
  const [showForcePwd, setShowForcePwd] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false); // [改进] 受控 Modal 替代 Modal.info
  const [showChangelog, setShowChangelog] = useState(false); // [改进] 版本更新记录弹窗

  // ---- 首次登录强制修改密码 ----
  useEffect(() => {
    if (isFirstLogin && !showChangePwd) {
      setShowForcePwd(true);
    }
  }, [isFirstLogin]);

  // ---- 导航权限过滤（扁平化后用于标题匹配） ----
  // [新增 2026-09-11] 支持权限数组：任一满足即可见（如「信息审核」同时服务注册审核与变更审核）
  const canShow = (perm?: NavPermission) =>
    !perm || (Array.isArray(perm) ? perm.some((p) => hasPermission(user, p)) : hasPermission(user, perm));

  const flatNav = navGroups
    .flatMap((g) => g.items)
    .filter((item) => canShow(item.permission));

  // [修复 2026-09-07] 汇总含子菜单的全部菜单项（子项独立鉴权）用于当前路由匹配；
  // 原先仅匹配顶级项，进入标识平面/标识设置的子页面（如 /signages、/campus-management）时
  // 无法命中任何菜单，选中态回退到「工作台」，浅绿色选中底纹消失
  const allNav = [
    ...flatNav,
    ...flatNav.flatMap((item) =>
      (item.children || []).filter((c) => canShow(c.permission))
    ),
  ];

  // [改进] 按路径长度降序排列：避免 /staff-rest-area 被 /staff 前缀误匹配，修复菜单高亮停留在「人员管理」的问题
  const sortedNav = [...allNav].sort((a, b) => b.path.length - a.path.length);

  // ---- 桌面端侧边栏折叠 / 移动端抽屉关闭 ----
  const handleNavClick = () => {
    setMobileDrawerOpen(false);
  };

  // 当前页面标题
  const pageTitle = sortedNav.find(
    (item) => location.pathname.startsWith(item.path)
  )?.label || '工作台';

  // [修复 2026-09-07] 受控展开：当前路由命中子菜单项时自动展开其父级子菜单，
  // 确保选中项可见；用户手动开合通过 onOpenKeysChange 正常生效
  const parentPathOfSelected = (() => {
    const hit = sortedNav.find((item) => location.pathname.startsWith(item.path));
    if (!hit) return undefined;
    return flatNav.find((item) => item.children?.some((c) => c.path === hit.path))?.path;
  })();

  const [openKeys, setOpenKeys] = useState<string[]>([]);
  useEffect(() => {
    if (parentPathOfSelected) {
      setOpenKeys((prev) => (prev.includes(parentPathOfSelected) ? prev : [...prev, parentPathOfSelected]));
    }
  }, [parentPathOfSelected]);

  // [修复 2026-09-07] 子菜单开合回调（antd v5 属性为 onOpenChange），同步受控展开状态
  const handleMenuOpenChange: NonNullable<MenuProps['onOpenChange']> = (keys) => {
    setOpenKeys(keys.map(String));
  };

  // ---- 退出登录 ----
  const handleLogout = useCallback(() => {
    logout();
    navigate('/login');
  }, [logout, navigate]);

  // ---- 5 分钟无操作自动退出 ----
  const idleTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const resetIdleTimer = useCallback(() => {
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    idleTimerRef.current = setTimeout(() => {
      handleLogout();
    }, IDLE_TIMEOUT);
  }, [handleLogout]);

  useEffect(() => {
    const events = ['mousedown', 'keydown', 'scroll', 'touchstart', 'mousemove'];
    resetIdleTimer();
    events.forEach((e) => document.addEventListener(e, resetIdleTimer));
    return () => {
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      events.forEach((e) => document.removeEventListener(e, resetIdleTimer));
    };
  }, [resetIdleTimer]);

  // ---- 用户下拉菜单 ----
  const userMenuItems: MenuProps['items'] = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人信息',
      onClick: () => navigate('/profile'),
    },
    {
      key: 'changePwd',
      icon: <LockOutlined />,
      label: '修改密码',
      onClick: () => setShowChangePwd(true),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ];

  // ---- 侧边栏导航菜单项（按分组生成，空分组剔除） ----
  // [修复 2026-09-03] 支持嵌套菜单，递归处理子菜单
  const processMenuItems = (items: Array<{
    path: string;
    // [修复 2026-09-09] 与 navGroups 保持一致：父菜单标签可为链接节点（点击「标识平面」跳转总览）
    label: string | React.ReactNode;
    icon: React.ReactNode;
    permission?: NavPermission;
    children?: Array<{
      path: string;
      label: string;
      icon: React.ReactNode;
      permission?: NavPermission;
    }>;
  // [修复 2026-09-05] 显式标注返回类型 ItemType[]：递归函数的返回类型无法被自动推断
  // （TS7023/7024/7022），需手工声明以打破循环引用
  }>): ItemType[] => {
    return items
      .filter((item) => canShow(item.permission))
      .map((item): ItemType => {
        // 如果有子菜单，递归处理
        if (item.children && item.children.length > 0) {
          const childItems = processMenuItems(item.children);
          // 如果子菜单全部被权限过滤掉了，则父菜单也不显示
          if (childItems.length === 0) return null;
          return {
            key: item.path,
            icon: item.icon,
            label: item.label,
            children: childItems,
          };
        }
        // 普通菜单项
        return {
          key: item.path,
          icon: item.icon,
          label: <Link to={item.path} onClick={handleNavClick}>{item.label}</Link>,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
  };

  const sidebarMenuItems: ItemType[] = navGroups
    .map((group) => {
      const children = processMenuItems(group.items);
      if (children.length === 0) return null;
      return { type: 'group' as const, label: group.title, children };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);

  // 当前选中的菜单项
  const selectedKey = sortedNav.find(
    (item) => location.pathname.startsWith(item.path)
  )?.path || '/dashboard';

  // ---- 侧边栏内容（桌面端和移动端共用） ----
  const sidebarContent = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 品牌 Logo 区域 */}
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 10,
          borderBottom: `1px solid ${SIDER.border}`,
          flexShrink: 0,
          padding: '0 16px',
        }}
      >
        {/* [调整 2026-09-10] 高度固定 34px，宽度按 Logo 原始比例伸缩；
            上限取 min(110px, 100%)，避免超宽 Logo 挤压右侧单位名称 */}
        <BrandLogo height={34} style={{ flexShrink: 0, maxWidth: 'min(110px, 100%)' }} />
        {!(desktopCollapsed && !isMobile) && (
          <Text
            strong
            style={{
              color: SIDER.text, fontSize: 15, lineHeight: 1.3, whiteSpace: 'nowrap',
              minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
            }}
          >
            {branding.orgNameCn}
          </Text>
        )}
      </div>

      {/* 导航菜单 */}
      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        openKeys={openKeys}
        onOpenChange={handleMenuOpenChange}
        items={sidebarMenuItems}
        style={{ flex: 1, borderRight: 0, overflowY: 'auto', background: 'transparent' }}
      />

      {/* 底部：折叠按钮 + 版本号 */}
      <div
        style={{
          flexShrink: 0,
          borderTop: `1px solid ${SIDER.border}`,
          padding: desktopCollapsed ? '8px 0' : '8px 0 4px',
          textAlign: 'center',
        }}
      >
        {!isMobile && (
          <Button
            type="text"
            icon={desktopCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setDesktopCollapsed(!desktopCollapsed)}
            style={{ color: SIDER.textSecondary, width: '100%' }}
            aria-label={desktopCollapsed ? '展开侧边栏' : '折叠侧边栏'}
          />
        )}
        {!desktopCollapsed && !isMobile && (
          <div
            onClick={() => setShowChangelog(true)} // [改进] 点击版本号查看更新记录
            title="查看版本更新记录"
            style={{
              fontSize: 12,
              color: SIDER.textTertiary,
              paddingBottom: 8,
              cursor: 'pointer',
              userSelect: 'none',
            }}
            className="version-link"
          >
            版本 {pkg.version}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 桌面端：Ant Design 侧边栏（浅色） */}
      {!isMobile && (
        <Sider
          collapsible
          collapsed={desktopCollapsed}
          onCollapse={setDesktopCollapsed}
          trigger={null}
          width={240}
          collapsedWidth={80}
          style={{
            overflow: 'hidden',
            height: '100vh',
            position: 'fixed',
            left: 0,
            top: 0,
            bottom: 0,
            zIndex: 100,
          }}
        >
          {sidebarContent}
        </Sider>
      )}

      {/* 移动端：Drawer 抽屉菜单（浅色） */}
      {isMobile && (
        <Drawer
          placement="left"
          open={mobileDrawerOpen}
          onClose={() => setMobileDrawerOpen(false)}
          width={260}
          styles={{ body: { padding: 0 } }}
          closeIcon={null}
        >
          <div style={{ background: SIDER.bg, height: '100%' }}>
            {sidebarContent}
          </div>
        </Drawer>
      )}

      {/* 右侧主区域 */}
      <Layout
        style={{
          marginLeft: isMobile ? 0 : (desktopCollapsed ? 80 : 240),
          transition: 'margin-left 0.2s',
        }}
      >
        {/* 顶部标题栏 */}
        <AntHeader
          style={{
            background: '#fff',
            borderBottom: `1px solid ${SIDER.border}`,
            padding: '0 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: 56,
            position: 'sticky',
            top: 0,
            zIndex: 99,
          }}
        >
          {/* 左侧：移动端汉堡按钮 + 页面标题 */}
          <Space align="center" size={12}>
            {isMobile && (
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={() => setMobileDrawerOpen(true)}
                aria-label="打开菜单"
              />
            )}
            <Text strong style={{ fontSize: 16, whiteSpace: 'nowrap' }}>
              {pageTitle}
            </Text>
          </Space>

          {/* 右侧：通知 + 用户信息 + 操作 */}
          <Space size={8}>
            <NotificationBell />

            {/* 用户下拉菜单 */}
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={['click']}>
              <Space
                align="center"
                size={8}
                style={{ cursor: 'pointer', padding: '4px 8px', borderRadius: 8 }}
                className="hover:bg-gray-50"
              >
                <Avatar
                  size={28}
                  style={{ backgroundColor: '#0E7F8A', flexShrink: 0 }}
                >
                  {user?.name?.[0] || 'U'}
                </Avatar>
                <span className="hidden sm:inline" style={{ fontSize: 14, color: SIDER.textSecondary }}>
                  {user?.name}
                </span>
              </Space>
            </Dropdown>

            {/* 角色标签 - 中屏以上显示 */}
            {user?.role && (
              <span
                className="hidden md:inline"
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  borderRadius: 4,
                  ...getRoleBadgeStyle(user.role),
                }}
              >
                {getRoleLabel(user.role)}
              </span>
            )}

            {/* 问题反馈 - 中屏以上显示 */}
            <Button
              type="link"
              size="small"
              className="hidden md:inline"
              onClick={() => setShowFeedback(true)}
              style={{ color: SIDER.textSecondary }}
            >
              问题反馈
            </Button>

            {/* 退出 - 始终显示 */}
            <Button
              type="link"
              size="small"
              danger
              onClick={handleLogout}
            >
              退出
            </Button>
          </Space>
        </AntHeader>

        {/* 内容区域 */}
        <Content style={{ padding: token.paddingLG, minHeight: 'calc(100vh - 56px)' }}>
          <LayoutContext.Provider value={{ sidebarCollapsed: isMobile ? true : desktopCollapsed }}>
            {children}
          </LayoutContext.Provider>
        </Content>
      </Layout>

      {/* 修改密码弹窗 */}
      <ChangePasswordModal
        open={showChangePwd}
        onClose={() => setShowChangePwd(false)}
      />

      {/* 首次登录强制修改密码弹窗 */}
      <ChangePasswordModal
        open={showForcePwd}
        onClose={() => {
          setShowForcePwd(false);
          if (user) {
            setUser({ ...user, must_change_password: false });
          }
        }}
        forceMode
      />

      {/* 问题反馈弹窗 - [改进] 使用受控 Modal 替代手写 div 遮罩 */}
      <Modal
        open={showFeedback}
        onCancel={() => setShowFeedback(false)}
        footer={null}
        centered
        width={380}
      >
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              backgroundColor: '#E3F4F6',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
            }}
          >
            <MessageOutlined style={{ fontSize: 28, color: '#0E7F8A' }} />
          </div>
          <Text style={{ fontSize: 14, color: '#5C6B7A', lineHeight: 1.6 }}>
            问题反馈请企业微信联系管理员
          </Text>
          <Button
            type="primary"
            block
            style={{ marginTop: 24 }}
            onClick={() => setShowFeedback(false)}
          >
            知道了
          </Button>
        </div>
      </Modal>

      {/* 版本更新记录弹窗 - [改进] 点击左下角版本号触发 */}
      <ChangelogModal
        open={showChangelog}
        onClose={() => setShowChangelog(false)}
      />
    </Layout>
  );
};

/**
 * [改进] 将 Tailwind 角色色值映射为内联样式，避免依赖 Tailwind JIT 类名
 */
function getRoleBadgeStyle(role: string): React.CSSProperties {
  const colorMap: Record<string, { bg: string; color: string }> = {
    admin_manager: { bg: '#FEE2E2', color: '#DC2626' },
    dept_manager:  { bg: '#FEF3E7', color: '#ED7B2F' },
    employee:      { bg: '#F3F4F6', color: '#6B7280' },
  };
  const style = colorMap[role] || { bg: '#F3F4F6', color: '#6B7280' };
  return { backgroundColor: style.bg, color: style.color };
}

export default AppLayout;
