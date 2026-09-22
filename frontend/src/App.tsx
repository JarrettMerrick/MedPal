// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { BrandingProvider } from './contexts/BrandingContext';
// [新增 2026-09-14] 功能开关 Provider（单位级功能启停，供菜单与入口显隐）
import { FeaturesProvider } from './contexts/FeaturesContext';
// [新增 2026-09-15] 待审核数量 Provider：左侧「信息审核」菜单角标 + 页内 Tab 角标共用
import { ReviewBadgeProvider } from './contexts/ReviewBadgeContext';
// [新增 2026-09-15] 站内信未读数 Provider：左侧「站内信」菜单红点 + 顶栏铃铛 + 站内信页共用
import { MessageUnreadProvider } from './contexts/MessageUnreadContext';
import ProtectedRoute from './components/ProtectedRoute';
import RoleGuard from './components/RoleGuard';
// [新增 2026-09-17] 功能开关路由守卫：单位级开关关闭后拦截页面直达（与左侧菜单同口径）
import FeatureRouteGuard from './components/FeatureRouteGuard';
import {
  PERM_USER_VIEW,
  PERM_DATA_EXPORT,
  PERM_STAFF_VIEW_RESIGNED,
  PERM_ROLE_VIEW,
  PERM_SYSTEM_CONFIG,
  PERM_USER_APPROVE,
  // [新增 2026-09-11] 人员信息变更审核（信息审核 → 信息变更审核 Tab）
  PERM_STAFF_APPROVE,
  // [新增 2026-09-11] 站内信
  PERM_MESSAGE_VIEW,
  PERM_STAFF_CREATE,
  PERM_STAFF_EDIT,
  PERM_DEPT_CREATE,
  PERM_DEPT_EDIT,
  PERM_REGULATION_CREATE,
  PERM_REGULATION_EDIT,
  PERM_SIGNAGE_VIEW,
  // [新增 2026-09-18] 标识总览独立权限（默认仅科室管理员/超管）
  PERM_SIGNAGE_OVERVIEW,
  PERM_SIGNAGE_CREATE,
  PERM_SIGNAGE_EDIT,
  // [修复 2026-09-07] 标识细粒度权限：子页面路由守卫按「标识平面/标识设置」细分
  PERM_SIGNAGE_MARKER,
  // [调整 2026-09-17] 移除 PERM_SIGNAGE_ALERT：「标识预警」页已下线
  PERM_SIGNAGE_INSPECTION,
  // [新增 2026-09-09] 维修记录（查看全部标识维修记录并导出）
  PERM_SIGNAGE_REPAIR,
  // [新增 2026-09-17] 文件库（设计文件集中管理）
  PERM_FILE_VIEW,
  PERM_SIGNAGE_FLOORPLAN,
  PERM_SIGNAGE_CAMPUS,
  PERM_SIGNAGE_CATEGORY,
  PERM_SIGNAGE_SUPPLIER,
  // [新增 2026-09-15] 通知设置访问权限（角色管理中位于「系统设置」分类）
  PERM_FEATURE_NOTIFICATION,
} from './utils/permissions';
import Layout from './components/Layout';
import Login from './pages/login/Login';
import Dashboard from './pages/Dashboard';
import DepartmentList from './pages/departments/DepartmentList';
import DepartmentForm from './pages/departments/DepartmentForm';
import DepartmentDetail from './pages/departments/DepartmentDetail';
import UserManage from './pages/users/UserManage';
import DataManage from './pages/data/DataManage';
import StaffRestArea from './pages/staff/StaffRestArea';
// [新增 2026-09-11] 站内信（统一消息中心）
import Messages from './pages/messages/Messages';
import StaffList from './pages/staff/StaffList';
import StaffForm from './pages/staff/StaffForm';
import StaffDetail from './pages/staff/StaffDetail';
import Profile from './pages/Profile';
import RegulationList from './pages/regulations/RegulationList';
import RegulationForm from './pages/regulations/RegulationForm';
import RegulationDetail from './pages/regulations/RegulationDetail';
import RoleList from './pages/roles/RoleList';
import SystemSettings from './pages/settings/SystemSettings';
// [新增 2026-09-14] 功能开关（单位级功能启停配置）
import FeatureSettings from './pages/settings/FeatureSettings';
// [新增 2026-09-15] 通知设置（按业务事件配置系统站内信的开关 / 文案 / 收件人）
import NotificationSettings from './pages/settings/NotificationSettings';
// [新增 2026-09-10] 账号设置、自助注册、信息审核
import AccountSettings from './pages/account-settings/AccountSettings';
import Register from './pages/register/Register';
import RegistrationReview from './pages/registration-review/RegistrationReview';
import SignageList from './pages/signages/SignageList';
import SignageForm from './pages/signages/SignageForm';
import SignageDetail from './pages/signages/SignageDetail';
// [修复 2026-09-05] 标识标记页面（重构自原平面图编辑）
import MarkerEditor from './pages/signages/MarkerEditor';
// [修复 2026-09-05] 平面设置页面
import PlanSettings from './pages/signages/PlanSettings';
import SignageHistoryPage from './pages/signages/SignageHistoryPage';
import SignageMobile from './pages/signages/SignageMobile';
// [删除 2026-09-17] 「标识预警」页已下线：状态异常标识与维修统一在「标识维修」页处理
// [新增 2026-09-09] 标识总览页（点击「标识平面」进入）与维修记录页
import SignageOverview from './pages/signages/SignageOverview';
import RepairRecords from './pages/signages/RepairRecords';
// [新增 2026-09-17] 文件管理（设计文件集中管理：检索 / 分类 / 标签 / 版本 / 标准设计文件）
import DesignFileManager from './pages/files/DesignFileManager';
import SignageExport from './pages/signages/SignageExport';
import CampusManagement from './pages/campus/CampusManagement';
// [修复 2026-09-04] 导入标识分类设置和供应商设置页面
import SignageCategorySettings from './pages/signages/SignageCategorySettings';
import SupplierSettings from './pages/signages/SupplierSettings';

const App: React.FC = () => {
  return (
    <BrowserRouter>
      {/* [新增 2026-09-10] 品牌 Provider 覆盖登录页（未认证）与所有已登录页面 */}
      <BrandingProvider>
        <AuthProvider>
          {/* [新增 2026-09-14] 功能开关 Provider：供给所有已登录页面的菜单与入口显隐判断 */}
          <FeaturesProvider>
          {/* [新增 2026-09-15] 待审核数量 Provider：信息审核菜单角标 + 页内 Tab 角标共用同一数据源 */}
          <ReviewBadgeProvider>
          {/* [新增 2026-09-15] 站内信未读数 Provider：菜单红点 / 顶栏铃铛 / 站内信页共用同一数据源 */}
          <MessageUnreadProvider>
          <Routes>
          <Route path="/login" element={<Login />} />
          {/* [新增 2026-09-10] 登录页自助注册（公开路由，是否开放由账号设置开关决定） */}
          <Route path="/register" element={<Register />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <Layout>
                  {/* [新增 2026-09-17] 功能开关路由守卫：被关闭的模块（标识平面/标识设置、制度牌、站内信）
                      不可通过直接输入 URL 进入，与左侧菜单隐藏保持同一口径 */}
                  <FeatureRouteGuard>
                  <Routes>
                    <Route path="/dashboard" element={<Dashboard />} />
                    {/* [新增 2026-09-11] 站内信（系统通知 + 群发/私发统一收件箱） */}
                    <Route
                      path="/messages"
                      element={
                        <RoleGuard permissions={[PERM_MESSAGE_VIEW]}>
                          <Messages />
                        </RoleGuard>
                      }
                    />
                    <Route path="/profile" element={<Profile />} />
                    <Route path="/staff" element={<StaffList />} />
                    {/* [修复] 写操作路由补充 RoleGuard：原先仅登录即可访问，靠页面内按钮隐藏，
                        无权限用户可构造请求直达写页面；allowSelf 保留「本人编辑自己」场景 */}
                    <Route
                      path="/staff/new"
                      element={
                        <RoleGuard permissions={[PERM_STAFF_CREATE]}>
                          <StaffForm />
                        </RoleGuard>
                      }
                    />
                    <Route
                      path="/staff/edit/:id"
                      element={
                        <RoleGuard permissions={[PERM_STAFF_EDIT]} allowSelf>
                          <StaffForm />
                        </RoleGuard>
                      }
                    />
                    <Route path="/staff/:id" element={<StaffDetail />} />
                    <Route path="/staff/view/:id" element={<StaffDetail />} />
                    <Route path="/departments" element={<DepartmentList />} />
                    <Route
                      path="/departments/new"
                      element={
                        <RoleGuard permissions={[PERM_DEPT_CREATE]}>
                          <DepartmentForm />
                        </RoleGuard>
                      }
                    />
                    <Route path="/departments/view/:id" element={<DepartmentDetail />} />
                    <Route
                      path="/departments/edit/:id"
                      element={
                        <RoleGuard permissions={[PERM_DEPT_EDIT]}>
                          <DepartmentForm />
                        </RoleGuard>
                      }
                    />
                    <Route
                      path="/users"
                      element={
                        <RoleGuard permissions={[PERM_USER_VIEW]}>
                          <UserManage />
                        </RoleGuard>
                      }
                    />
                    <Route
                      path="/data"
                      element={
                        <RoleGuard permissions={[PERM_DATA_EXPORT]}>
                          <DataManage />
                        </RoleGuard>
                      }
                    />
                    <Route
                      path="/staff-rest-area"
                      element={
                        <RoleGuard permissions={[PERM_STAFF_VIEW_RESIGNED]}>
                          <StaffRestArea />
                        </RoleGuard>
                      }
                    />
                    <Route
                      path="/roles"
                      element={
                        <RoleGuard permissions={[PERM_ROLE_VIEW]}>
                          <RoleList />
                        </RoleGuard>
                      }
                    />
                    {/* [新增 2026-09-10] 单位设置（单位 Logo / 单位名称 / 系统名称） */}
                    <Route
                      path="/system-settings"
                      element={
                        <RoleGuard permissions={[PERM_SYSTEM_CONFIG]}>
                          <SystemSettings />
                        </RoleGuard>
                      }
                    />
                    {/* [新增 2026-09-14] 功能开关（单位级功能启停；与角色管理中的 feature.* 权限两层控制） */}
                    <Route
                      path="/feature-settings"
                      element={
                        <RoleGuard permissions={[PERM_SYSTEM_CONFIG]}>
                          <FeatureSettings />
                        </RoleGuard>
                      }
                    />
                    {/* [新增 2026-09-15] 通知设置（按业务事件配置开关 / 文案 / 收件人） */}
                    {/* [调整 2026-09-15] 门禁由 system.config 改为独立权限点 feature.notification，
                        与角色管理「系统设置」分类下的「通知设置」权限项一一对应 */}
                    <Route
                      path="/notification-settings"
                      element={
                        <RoleGuard permissions={[PERM_FEATURE_NOTIFICATION]}>
                          <NotificationSettings />
                        </RoleGuard>
                      }
                    />
                    {/* [新增 2026-09-10] 账号设置（默认密码规则 / 登录页注册开关） */}
                    <Route
                      path="/account-settings"
                      element={
                        <RoleGuard permissions={[PERM_SYSTEM_CONFIG]}>
                          <AccountSettings />
                        </RoleGuard>
                      }
                    />
                    {/* [调整 2026-09-11] 信息审核：账号注册审核（user.approve）+
                        信息变更审核（staff.approve），具备任一权限即可进入（页内按权限显示 Tab） */}
                    <Route
                      path="/registration-review"
                      element={
                        <RoleGuard permissions={[PERM_USER_APPROVE, PERM_STAFF_APPROVE]}>
                          <RegistrationReview />
                        </RoleGuard>
                      }
                    />
                    <Route path="/regulations" element={<RegulationList />} />
                    {/* [修复] 制度写操作路由补充 RoleGuard */}
                    <Route
                      path="/regulations/new"
                      element={
                        <RoleGuard permissions={[PERM_REGULATION_CREATE]}>
                          <RegulationForm />
                        </RoleGuard>
                      }
                    />
                    <Route path="/regulations/view/:id" element={<RegulationDetail />} />
                    <Route
                      path="/regulations/edit/:id"
                      element={
                        <RoleGuard permissions={[PERM_REGULATION_EDIT]}>
                          <RegulationForm />
                        </RoleGuard>
                      }
                    />
                    {/* [新增 2026-09-03] 标识管理路由 */}
                    <Route path="/signages" element={<SignageList />} />
                    {/* [新增 2026-09-09] 标识总览与维修记录（signage.repair） */}
                    {/* [调整 2026-09-18] 总览门禁由 signage.view 改为独立的 signage.overview：
                        默认仅科室管理员与超级管理员拥有，普通员工访问会被守卫弹回工作台 */}
                    <Route path="/signage-overview" element={<RoleGuard permissions={[PERM_SIGNAGE_OVERVIEW]}><SignageOverview /></RoleGuard>} />
                    <Route path="/signage-repairs" element={<RoleGuard permissions={[PERM_SIGNAGE_REPAIR]}><RepairRecords /></RoleGuard>} />
                    <Route path="/signages/new" element={<RoleGuard permissions={[PERM_SIGNAGE_CREATE]}><SignageForm /></RoleGuard>} />
                    <Route path="/signages/:id" element={<SignageDetail />} />
                    <Route path="/signages/view/:id" element={<SignageDetail />} />
                    <Route path="/signages/edit/:id" element={<RoleGuard permissions={[PERM_SIGNAGE_EDIT]}><SignageForm /></RoleGuard>} />
                    {/* [新增 2026-09-09] 版本更新入口：复用标识表单，保存后修改会写入历史版本（record_history=true） */}
                    <Route path="/signages/version-update/:id" element={<RoleGuard permissions={[PERM_SIGNAGE_EDIT]}><SignageForm recordHistory /></RoleGuard>} />
                    <Route path="/signages/:id/history" element={<SignageHistoryPage />} />
                    {/* [修复 2026-09-07] 标识子页面路由守卫按细粒度权限拆分（标识平面/标识设置） */}
                    <Route path="/signage-floorplan" element={<RoleGuard permissions={[PERM_SIGNAGE_MARKER]}><MarkerEditor /></RoleGuard>} />
                    <Route path="/signage-mobile" element={<RoleGuard permissions={[PERM_SIGNAGE_INSPECTION]}><SignageMobile /></RoleGuard>} />
                    {/* [删除 2026-09-17] /signage-alerts 路由已下线（预警页移除，能力并入「标识维修」） */}
                    <Route path="/signage-export" element={<SignageExport />} />
                    {/* [新增 2026-09-17] 文件管理（文件库）：需 file.view 权限 */}
                    <Route path="/design-files" element={<RoleGuard permissions={[PERM_FILE_VIEW]}><DesignFileManager /></RoleGuard>} />
                    {/* [修复 2026-09-03] 院区管理路由 */}
                    <Route path="/campus-management" element={<RoleGuard permissions={[PERM_SIGNAGE_CAMPUS]}><CampusManagement /></RoleGuard>} />
                    {/* [修复 2026-09-05] 平面设置路由（迁入标识设置菜单） */}
                    <Route path="/signage-plan-settings" element={<RoleGuard permissions={[PERM_SIGNAGE_FLOORPLAN]}><PlanSettings /></RoleGuard>} />
                    {/* [修复 2026-09-04] 标识分类设置路由 */}
                    <Route path="/signage-categories" element={<RoleGuard permissions={[PERM_SIGNAGE_CATEGORY]}><SignageCategorySettings /></RoleGuard>} />
                    {/* [修复 2026-09-04] 供应商设置路由 */}
                    <Route path="/suppliers" element={<RoleGuard permissions={[PERM_SIGNAGE_SUPPLIER]}><SupplierSettings /></RoleGuard>} />
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                  </Routes>
                  </FeatureRouteGuard>
                </Layout>
              </ProtectedRoute>
            }
          />
          </Routes>
          </MessageUnreadProvider>
          </ReviewBadgeProvider>
          </FeaturesProvider>
        </AuthProvider>
      </BrandingProvider>
    </BrowserRouter>
  );
};

export default App;
