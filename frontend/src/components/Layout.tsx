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
 * - [改进] 侧边栏由深色 #001529 改为浅色轻盈风格，品牌区使用统一 BrandLogo 组件
 *   （[调整 2026-09-16] 默认样式改为代码绘制，不再依赖内置位图 MedPal_Logo.png）
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
// [调整 2026-09-14] 站内信/标识/制度菜单入口统一改用**单一功能开关权限点** feature.access
// （同时受「系统设置 → 功能开关」按模块分别约束，见 canShow），功能内部操作仍由细粒度权限控制
// [调整 2026-09-15] 模块入口（站内信/制度管理/标识平面/标识设置）的角色级门禁改为**细粒度权限**驱动：
// 原先统一用「功能开关」权限点 feature.access，导致按角色单独授予「标识巡检」等细粒度权限后菜单仍不可见
// （feature.access 默认仅超管）。单位级「功能开关」仍由各项的 feature 字段控制，不受影响。
// [调整 2026-09-17] 移除 PERM_SIGNAGE_ALERT：「标识预警」菜单已下线（能力并入「标识维修」页）
import { hasPermission, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_OVERVIEW, PERM_SIGNAGE_MARKER, PERM_SIGNAGE_INSPECTION, PERM_SIGNAGE_REPAIR, PERM_SIGNAGE_FLOORPLAN, PERM_SIGNAGE_CAMPUS, PERM_SIGNAGE_CATEGORY, PERM_SIGNAGE_SUPPLIER, PERM_STAFF_VIEW_RESIGNED, PERM_DATA_EXPORT, PERM_USER_VIEW, PERM_ROLE_VIEW, PERM_SYSTEM_CONFIG, PERM_USER_APPROVE, PERM_STAFF_APPROVE, PERM_FEATURE_NOTIFICATION, PERM_MESSAGE_VIEW, PERM_REGULATION_VIEW, PERM_FILE_VIEW } from '../utils/permissions';
import useMediaQuery from '../hooks/useMediaQuery'; // [改进] 响应式断点 Hook
import ChangePasswordModal from './ChangePasswordModal';
import NotificationBell from './NotificationBell';
import ChangelogModal from './ChangelogModal'; // [改进] 版本更新记录弹窗
// [新增 2026-09-15] 未审核条数角标（红底白字）：展示「信息审核」菜单的待办数量
import ReviewCountBadge from './ReviewCountBadge';
// [调整 2026-09-10] 统一品牌 Logo 组件：显示高度固定、宽度按 Logo 原始比例等比伸缩
import BrandLogo from './BrandLogo';
// [新增 2026-09-10] 全局品牌信息（单位名称 / 已上传 Logo）
import { useBranding } from '../contexts/BrandingContext';
// [新增 2026-09-14] 全局功能开关（单位级功能启停，控制菜单与入口显隐）
import { useFeatures } from '../contexts/FeaturesContext';
// [新增 2026-09-15] 待审核数量（「信息审核」菜单角标；与信息审核页内 Tab 共用同一数据源）
import { useReviewBadge } from '../contexts/ReviewBadgeContext';
// [新增 2026-09-15] 站内信未读数（「站内信」菜单红点；与顶栏铃铛、站内信页共用同一数据源）
import { useMessageUnread } from '../contexts/MessageUnreadContext';


// [新增 2026-09-14] 功能标识类型（'messages' | 'signage' | 'regulation'），标注菜单受哪个开关约束
import type { FeatureKey } from '../api/features';
// [新增 2026-09-19] 界面外观偏好（新拟物/经典 × 浅色/深色）：用于在用户菜单中提供切换入口
import { useUiPrefs } from '../contexts/UiPrefsContext';

// [改进] Ant Design 组件（全部本地化，内网可用）
import { Layout, Menu, Button, Dropdown, Space, Modal, Typography, Drawer, Avatar, theme } from 'antd';
import type { MenuProps } from 'antd';
import {
  HomeOutlined, TeamOutlined, BankOutlined, FileTextOutlined,
  UserDeleteOutlined, DatabaseOutlined, UserOutlined,
  // [新增 2026-09-17] 文件管理菜单图标
  FolderOpenOutlined,
  // [新增 2026-09-19] 界面外观切换入口图标（新拟物/经典、明暗模式）
  BgColorsOutlined, BulbOutlined,
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
  // [新增 2026-09-14] 功能开关菜单图标
  ControlOutlined,
  // [新增 2026-09-15] 通知设置菜单图标
  NotificationOutlined,
} from '@ant-design/icons';
import type { ItemType } from 'antd/es/menu/interface';
import pkg from '../../package.json'; // [改进] 从 package.json 读取版本号，避免硬编码导致发版遗漏（路径需指向 frontend 根目录）

const { Sider, Header: AntHeader, Content } = Layout;
const { Text } = Typography;

// ==================== 常量 ====================

/**
 * [改进] 侧边栏配色（医疗青蓝 token 体系）
 *
 * [改造 2026-09-19] 由硬编码色值改为**引用 CSS 变量**（见 theme/neu-tokens.css）：
 *   - 新拟物模式：与页面底同色，靠双向阴影表达凸起，无边框；
 *   - 经典模式：自动退回原来的白色 + 细边框；
 *   - 深色模式：自动切换为深底与浅色文字。
 * 因为是 CSS 变量，内联样式同样生效，且**无需在 JS 中感知当前模式**。
 */
const SIDER = {
  bg: 'var(--neu-bg)',
  border: 'var(--line-softer)',
  text: 'var(--text-1)',
  textSecondary: 'var(--text-2)',
  textTertiary: 'var(--text-3)',
  /** 品牌渐变为品牌资产，不随外观模式切换 */
  logoBg: 'linear-gradient(135deg, #0E7F8A, #0A6771)',
} as const;

/** [新增 2026-09-11] 菜单权限：支持单个权限或权限数组（数组 = 任一满足即可显示） */
type NavPermission = string | string[];

/**
 * [新增 2026-09-17] 菜单角标类型（原先在两处内联重复定义，统一收敛到此处）：
 *   'review' = 「信息审核」待审数量
 *   'unread' = 「站内信」未读数量
 *   'alert'  = 「标识预警」待处理预警数量
 */
type NavBadgeKind = 'review' | 'unread' | 'alert';

/** [改进] 导航配置：按「概览 / 业务 / 系统」分组，icon 使用 @ant-design/icons（内嵌 SVG，不需要外部资源） */
const navGroups: Array<{
  title: string;
  items: Array<{
    path: string;
    // [修复 2026-09-09] 父菜单标签改为链接节点（点击「标识平面」直接进入标识总览）
    label: string | React.ReactNode;
    icon: React.ReactNode;
    permission?: NavPermission;
    /** [新增 2026-09-14] 该菜单受哪个单位级功能开关约束（与 permission 共同生效，见 canShow） */
    feature?: FeatureKey;
    /**
     * [新增 2026-09-15] 待办 / 未读角标类型（取值见 NavBadgeKind）：
     *   'review' = 「信息审核」待审数量；'unread' = 「站内信」未读数；
     *   'alert'  = 「标识预警」待处理预警数（[新增 2026-09-17]）。
     * 只声明"要挂哪种角标"，具体数值在渲染时从对应 Context 读取，
     * 避免把动态数量写进这份静态导航配置。
     */
    badge?: NavBadgeKind;
    children?: Array<{
      path: string;
      label: string;
      icon: React.ReactNode;
      permission?: NavPermission;
      feature?: FeatureKey;
      /** [新增 2026-09-17] 子菜单项同样支持角标（如「标识预警」） */
      badge?: NavBadgeKind;
    }>;
  }>;
}> = [
  {
    title: '概览',
    items: [
      { path: '/dashboard', label: '工作台', icon: <HomeOutlined /> },
      // [新增 2026-09-11] 站内信：系统通知 + 管理员群发/私发的统一收件箱
      // [调整 2026-09-15] 门禁改为细粒度权限 message.view；feature 指明其受哪个单位级开关控制
      // [新增 2026-09-15] 未读红点：显示未读站内信数量（与顶栏铃铛、站内信页同源）
      { path: '/messages', label: '站内信', icon: <MessageOutlined />, permission: PERM_MESSAGE_VIEW, feature: 'messages', badge: 'unread' },
    ],
  },
  {
    title: '业务',
    items: [
      { path: '/staff', label: '人员管理', icon: <TeamOutlined /> },
      { path: '/departments', label: '科室管理', icon: <BankOutlined /> },
      // [调整 2026-09-14] 「制度管理」门禁为功能开关权限点 feature.access，受「制度牌」开关控制
      { path: '/regulations', label: '制度管理', icon: <FileTextOutlined />, permission: PERM_REGULATION_VIEW, feature: 'regulation' },
      // [修复 2026-09-04] 标识平面菜单，将标识相关菜单项移入子菜单
      // [修复 2026-09-07] 子菜单门禁按细粒度权限拆分（标识管理/标识标记/标识预警/标识巡检）
      {
        path: '/signage-workspace',
        // [修复 2026-09-09] 点击「标识平面」直接跳转到标识总览（同时保留展开子菜单行为）
        // [调整 2026-09-18] 跳转目标改为按权限动态决定：总览已改为独立权限（默认仅科室管理员/超管），
        // 这里只作占位，实际跳转见 processMenuItems 中的 signageHomePath
        label: <Link to="/signage-overview">标识平面</Link>,
        icon: <TagsOutlined />,
        // [调整 2026-09-15] 分组级门禁：标识细粒度权限任一 +「标识平面与标识设置」单位级开关
        // （原先为 feature.access，会使仅有「标识巡检」等细粒度权限的角色看不到入口）
        // [调整 2026-09-18] 补入标识总览权限：仅有总览权限的角色同样应看到分组入口
        permission: [PERM_SIGNAGE_OVERVIEW, PERM_SIGNAGE_VIEW, PERM_SIGNAGE_MARKER, PERM_SIGNAGE_INSPECTION, PERM_SIGNAGE_REPAIR],
        feature: 'signage',
        children: [
          // [调整 2026-09-18] 门禁由 signage.view 改为独立的 signage.overview（默认仅科室管理员/超管）
          { path: '/signage-overview', label: '标识总览', icon: <DashboardOutlined />, permission: PERM_SIGNAGE_OVERVIEW },
          { path: '/signages', label: '标识管理', icon: <TagsOutlined />, permission: PERM_SIGNAGE_VIEW },
          { path: '/signage-floorplan', label: '标识标记', icon: <ApartmentOutlined />, permission: PERM_SIGNAGE_MARKER },
          // [调整 2026-09-17] 「维修记录」更名为「标识维修」：页面同时承载
          // 待维修标识（轻微破损 / 严重损坏）与维修记录，可直接发起 / 完成维修
          { path: '/signage-repairs', label: '标识维修', icon: <ToolOutlined />, permission: PERM_SIGNAGE_REPAIR },
          // [删除 2026-09-17] 「标识预警」菜单已下线：预警能力并入「标识维修」页
          // [新增 2026-09-17] 文件管理：设计文件集中管理（检索 / 分类 / 标签 / 版本 / 标准设计文件复用）
          { path: '/design-files', label: '文件管理', icon: <FolderOpenOutlined />, permission: PERM_FILE_VIEW },
          { path: '/signage-mobile', label: '标识巡检', icon: <MobileOutlined />, permission: PERM_SIGNAGE_INSPECTION },
        ],
      },
      // [调整 2026-09-11] 「员工休息区」更名为「离职人员」（语义更直白：离职档案 + 保留期管理）
      { path: '/staff-rest-area', label: '离职人员', icon: <UserDeleteOutlined />, permission: PERM_STAFF_VIEW_RESIGNED },
      // [调整 2026-09-11] 「信息审核」合并两个 Tab：账号注册审核（user.approve）+
      // 信息变更审核（staff.approve）；具备任一权限即可见（页内按权限只显示对应 Tab）
      // [新增 2026-09-15] 挂待办角标：显示两项待审数量之和（有几条未审核就显示几个数字，红底白字）
      {
        path: '/registration-review',
        label: '信息审核',
        icon: <AuditOutlined />,
        permission: [PERM_USER_APPROVE, PERM_STAFF_APPROVE],
        badge: 'review',
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
        // [调整 2026-09-15] 分组级门禁：标识设置细粒度权限任一 + 同一单位级开关
        // （无任何标识设置权限的角色自动看不到本分组）
        permission: [PERM_SIGNAGE_CAMPUS, PERM_SIGNAGE_FLOORPLAN, PERM_SIGNAGE_CATEGORY, PERM_SIGNAGE_SUPPLIER],
        feature: 'signage',
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
          // [新增 2026-09-14] 功能开关：单位级功能启停（站内信 / 标识平面与标识设置）
          { path: '/feature-settings', label: '功能开关', icon: <ControlOutlined />, permission: PERM_SYSTEM_CONFIG },
          // [新增 2026-09-15] 通知设置：按业务事件配置系统站内信的开关 / 文案 / 收件人
          // [调整 2026-09-15] 门禁改为独立权限点 feature.notification（角色管理 →「系统设置」分类）
          { path: '/notification-settings', label: '通知设置', icon: <NotificationOutlined />, permission: PERM_FEATURE_NOTIFICATION },
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
  // [新增 2026-09-17] isPendingReview：自助注册账号在审核通过前仅可访问个人信息
  const { user, logout, isFirstLogin, isPendingReview, setUser } = useAuth();
  const branding = useBranding(); // [新增 2026-09-10] 单位 Logo 与单位名称
  const features = useFeatures(); // [新增 2026-09-14] 功能开关（站内信 / 标识平面与标识设置）
  // [新增 2026-09-15] 「信息审核」菜单角标数据：两项待审数量之和（与页内 Tab 同源，保证数字一致）
  const { total: reviewBadgeTotal } = useReviewBadge();
  // [新增 2026-09-15] 「站内信」菜单红点数据：未读数量（与顶栏铃铛、站内信页同源）
  const { unread: unreadBadgeTotal } = useMessageUnread();


  const location = useLocation();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  // [新增 2026-09-19] 界面外观偏好：供用户菜单切换「新拟物 / 经典」与「浅色 / 深色」
  const { isNeu, isDark, toggleUiStyle, toggleColorMode } = useUiPrefs();

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

  // ---- [新增 2026-09-17] 待审核账号：统一收敛到「个人信息」页 ----
  // 自助注册后账号即可登录，但审核通过前后端仅放行认证与本人资料接口；
  // 这里把侧边栏精简为「个人信息」一项，并自动跳转，避免点击其他菜单被 403。
  useEffect(() => {
    if (isPendingReview && location.pathname !== '/profile') {
      navigate('/profile', { replace: true });
    }
  }, [isPendingReview, location.pathname, navigate]);

  // ---- 导航权限过滤（扁平化后用于标题匹配） ----
  // [新增 2026-09-11] 支持权限数组：任一满足即可见（如「信息审核」同时服务注册审核与变更审核）
  // [调整 2026-09-15] 受功能开关管控的模块入口采用两层控制：
  //   1) 单位级「功能开关」——由 item.feature 指明该菜单受哪个开关约束，关闭则对所有人隐藏；
  //   2) 角色级**细粒度权限**——站内信用 message.view、制度用 regulation.view、
  //      标识平面用标识类权限（任一）、标识设置用设置类权限（任一）。
  //      原先统一用功能开关权限点 feature.access，会使仅有细粒度权限的角色看不到入口。
  //   后端对应接口同样会返回 403，前端隐藏仅用于保持一致体验。
  const canShow = (perm?: NavPermission, feature?: FeatureKey) => {
    if (feature && !features.isEnabled(feature)) return false;
    const list = perm ? (Array.isArray(perm) ? perm : [perm]) : [];
    return !perm || list.some((p) => hasPermission(user, p));
  };

  /**
   * [新增 2026-09-18] 「标识平面」父菜单的跳转目标。
   *
   * 原先固定跳「标识总览」，但总览已改为独立权限（默认仅科室管理员 / 超管）；
   * 普通员工点击父项会被路由守卫直接弹回工作台，看起来像"点了没反应还跳走了"。
   * 现按权限顺序取第一个可访问的子页面，兜底回工作台。
   */
  const signageHomePath = (() => {
    const candidates: Array<[string, string]> = [
      ['/signage-overview', PERM_SIGNAGE_OVERVIEW],
      ['/signages', PERM_SIGNAGE_VIEW],
      ['/signage-floorplan', PERM_SIGNAGE_MARKER],
      ['/signage-repairs', PERM_SIGNAGE_REPAIR],
      ['/design-files', PERM_FILE_VIEW],
      ['/signage-mobile', PERM_SIGNAGE_INSPECTION],
    ];
    return candidates.find(([, perm]) => hasPermission(user, perm))?.[0] || '/dashboard';
  })();

  const flatNav = navGroups
    .flatMap((g) => g.items)
    .filter((item) => canShow(item.permission, item.feature));

  // [修复 2026-09-07] 汇总含子菜单的全部菜单项（子项独立鉴权）用于当前路由匹配；
  // 原先仅匹配顶级项，进入标识平面/标识设置的子页面（如 /signages、/campus-management）时
  // 无法命中任何菜单，选中态回退到「工作台」，浅绿色选中底纹消失
  const allNav = [
    ...flatNav,
    ...flatNav.flatMap((item) =>
      (item.children || []).filter((c) => canShow(c.permission, c.feature))
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
    // [新增 2026-09-19] 界面外观切换入口：即时生效并记忆（localStorage），
    // 便于用户按偏好选择与随时回退（新拟物对比度偏低，保留经典作为兜底选项）
    {
      key: 'uiStyle',
      // [文案调整 2026-09-21] 显示名改为「传统 / 时尚」，更贴合用户直觉：
      //   时尚 = neu（新拟物，本项目的目标视觉）
      //   传统 = classic（改造前的旧样式）
      // 仅改显示文案，内部取值仍是 'neu' / 'classic'，不影响任何样式规则与已保存的偏好。
      icon: <BgColorsOutlined />,
      label: `界面风格：${isNeu ? '时尚' : '传统'}`,
      onClick: toggleUiStyle,
    },
    {
      key: 'colorMode',
      // [文案调整 2026-09-21] 显示名改为「白天 / 黑夜」，
      //   白天 = light（浅色）· 黑夜 = dark（深色）
      icon: <BulbOutlined />,
      label: `明暗模式：${isDark ? '黑夜' : '白天'}`,
      onClick: toggleColorMode,
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
    /** [新增 2026-09-14] 该菜单受哪个单位级功能开关约束（与 permission 共同生效） */
    feature?: FeatureKey;
    /** [新增 2026-09-15] 角标类型（取值见 NavBadgeKind）：信息审核待审数 / 站内信未读数 / 标识预警数 */
    badge?: NavBadgeKind;
    children?: Array<{
      path: string;
      label: string;
      icon: React.ReactNode;
      permission?: NavPermission;
      feature?: FeatureKey;
      /** [新增 2026-09-17] 子菜单项同样支持角标（如「标识预警」） */
      badge?: NavBadgeKind;
    }>;
  // [修复 2026-09-05] 显式标注返回类型 ItemType[]：递归函数的返回类型无法被自动推断
  // （TS7023/7024/7022），需手工声明以打破循环引用
  // [新增 2026-09-17] 新增 depth 参数（0 = 顶层）：用于区分「折叠态是否需要图标角标」，
  // 子菜单在折叠态的弹出浮层中始终显示文字，只保留文字角标即可，避免出现两个红点
  }>, depth = 0): ItemType[] => {
    return items
      .filter((item) => canShow(item.permission, item.feature))
      .map((item): ItemType => {
        // 如果有子菜单，递归处理
        if (item.children && item.children.length > 0) {
          const childItems = processMenuItems(item.children, depth + 1);
          // 如果子菜单全部被权限过滤掉了，则父菜单也不显示
          if (childItems.length === 0) return null;
          return {
            key: item.path,
            icon: item.icon,
            // [新增 2026-09-18] 「标识平面」父项按权限动态决定跳转目标（见 signageHomePath），
            // 其余父项保持静态 label 不变
            label: item.path === '/signage-workspace'
              ? <Link to={signageHomePath}>标识平面</Link>
              : item.label,
            children: childItems,
          };
        }
        // [新增 2026-09-15] 角标计数（信息审核待审 / 站内信未读）：数量为 0 时角标组件自身不渲染
        // [调整 2026-09-17] 移除 'alert' 分支：「标识预警」菜单已下线
        const badgeCount = item.badge === 'review' ? reviewBadgeTotal
          : item.badge === 'unread' ? unreadBadgeTotal : 0;
        // 侧边栏折叠时 antd 会隐藏菜单文字，此时把角标挂到图标右上角，避免待办完全不可见。
        // [新增 2026-09-17] 仅顶层菜单项需要这样做：子菜单在折叠态的弹出浮层中
        // 始终显示文字，label 内的角标已经可见，再挂图标角标会出现两个红点。
        const collapsedNow = desktopCollapsed && !isMobile && depth === 0;

        // 普通菜单项
        return {
          key: item.path,
          icon: badgeCount > 0 && collapsedNow ? (
            <ReviewCountBadge count={badgeCount} size="small" offset={[0, -2]}>
              {item.icon}
            </ReviewCountBadge>
          ) : item.icon,
          label: (
            <Link to={item.path} onClick={handleNavClick}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {item.label}
                {/* 角标紧跟在菜单文字右侧，红底白字显示待审条数 */}
                <ReviewCountBadge count={badgeCount} size="small" />
              </span>
            </Link>
          ),
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
  };

  // [新增 2026-09-17] 待审核账号（自助注册未通过审核）的侧边栏：
  // 仅保留「个人信息」一项 —— 后端中间件同样只放行本人资料相关接口，
  // 这里保持一致的体验，避免用户点击其他入口后收到 403。
  const pendingReviewMenuItems: ItemType[] = [
    {
      type: 'group' as const,
      label: '账号',
      children: [
        {
          key: '/profile',
          icon: <UserOutlined />,
          label: (
            <Link to="/profile" onClick={handleNavClick}>
              个人信息
            </Link>
          ),
        },
      ],
    },
  ];

  const sidebarMenuItems: ItemType[] = isPendingReview
    ? pendingReviewMenuItems
    : navGroups
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
      {/* [调整 2026-09-19] 加 className="sider-brand"：新拟物模式下由
          theme/neumorphism.css 改写为「凸起品牌块」（去描边、加圆角与双向阴影），
          经典模式下不受影响（规则均限定在 [data-ui-style='neu'] 作用域内）。 */}
      <div
        className="sider-brand"
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
      {/* [调整 2026-09-19] 加 className="sider-footer"：拟物模式下改为凸起块（同上） */}
      <div
        className="sider-footer"
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
        {/* [改造 2026-09-19] 顶栏底色改引用变量（拟物下与页面底同色），
            下边框改为极浅同色分界（拟物下进一步弱化，见 neumorphism.css） */}
        <AntHeader
          className="app-header"
          style={{
            background: SIDER.bg,
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
            {/* [调整 2026-09-14] 站内信功能关闭时隐藏消息铃铛：避免入口残留与无效的未读数轮询
                [新增 2026-09-17] 待审核账号（自助注册）同样隐藏：后端仅放行本人资料接口 */}
            {features.isEnabled('messages') && !isPendingReview && <NotificationBell />}

            {/* 用户下拉菜单 */}
            <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={['click']}>
              {/* [改造 2026-09-19] 原用 Tailwind 调色板类 hover:bg-gray-50（深色下失效），
                  改用变量驱动的 .neu-user-chip：拟物下悬停为浅青凹陷底，深色自动适配 */}
              <Space
                align="center"
                size={8}
                style={{ cursor: 'pointer', padding: '4px 10px', borderRadius: 'var(--radius-control)' }}
                className="neu-user-chip"
              >
                <Avatar
                  size={28}
                  style={{ backgroundColor: 'var(--accent)', flexShrink: 0 }}
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
        {/* [调整 2026-09-12] 改为纵向 flex 容器：内容不足一屏时让页脚标语贴底，
            内容超长时随内容自然下移（不遮挡任何内容） */}
        {/*
          [修复 2026-09-19] 消除页面级横向滚动条：
          Content 是 Layout（flex 容器）的子项，而 flex 子项默认 min-width: auto
          —— 不会收缩到内容宽度以下。表格的 scroll={{ x: 1400 }} 会把它撑到 1400px，
          导致**整页**出现横向滚动条（而非表格内部滚动）。min-width: 0 解除该限制，
          让 Content 收缩到可用宽度，超宽内容交由表格自身滚动。
          padding 由内联改为 .app-content 类，以便窄屏通过媒体查询收紧。
        */}
        <Content
          className="app-content"
          style={{
            minHeight: 'calc(100vh - 56px)',
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
          }}
        >
          <LayoutContext.Provider value={{ sidebarCollapsed: isMobile ? true : desktopCollapsed }}>
            {children}
          </LayoutContext.Provider>

          {/* [新增 2026-09-12] 页脚宣传标语：marginTop:auto 吸收多余空间实现贴底。
              未配置或管理员主动清空时整块不渲染；配色沿用侧边栏「版本 x.x.x」的弱化色 */}
          {branding.slogan && (
            <div
              style={{
                marginTop: 'auto',
                paddingTop: token.paddingLG,
                textAlign: 'center',
                fontSize: token.fontSizeSM,
                color: SIDER.textTertiary,
                flexShrink: 0,
              }}
            >
              {branding.slogan}
            </div>
          )}
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
              /* [改造 2026-09-19] 硬编码色改引用变量，深色下自动适配 */
              backgroundColor: 'var(--accent-soft)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
            }}
          >
            <MessageOutlined style={{ fontSize: 28, color: 'var(--accent)' }} />
          </div>
          <Text style={{ fontSize: 14, color: 'var(--text-2)', lineHeight: 1.6 }}>
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
 *
 * [改造 2026-09-19] 保留「超管红 / 科室管理员橙 / 员工灰」的角色语义色相不变，
 * 但底与字改引用变量：原先的浅底（#FEE2E2 / #FEF3E7 / #F3F4F6）在深色页面上
 * 会形成刺眼的亮块，且深色下亮底 + 深字的对比度不足。改为语义色变量后，
 * 浅色下观感与改造前近似，深色下自动切换为半透明彩底 + 提亮字色。
 */
function getRoleBadgeStyle(role: string): React.CSSProperties {
  const colorMap: Record<string, { bg: string; color: string }> = {
    admin_manager: { bg: 'var(--danger-soft)', color: 'var(--danger)' },
    dept_manager:  { bg: 'var(--warn-soft)', color: 'var(--warn)' },
    employee:      { bg: 'var(--line-softer)', color: 'var(--text-2)' },
  };
  const style = colorMap[role] || { bg: 'var(--line-softer)', color: 'var(--text-2)' };
  return { backgroundColor: style.bg, color: style.color };
}

export default AppLayout;
