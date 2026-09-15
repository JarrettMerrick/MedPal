# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""角色初始化和数据库升级兼容代码（与 CRUD 分离）"""

import logging
from sqlalchemy.orm import Session

from app.models.role import Role, Permission

logger = logging.getLogger("role_initializer")


def init_default_roles(db: Session):
    """初始化默认角色和权限
    
    [改进] 每次启动都执行以下安全检查：
    1. 补充新增权限
    2. 验证所有用户的角色名有效性并自动修正
    3. 同步有效角色名到 User 模型的 ORM 校验器
    """
    if db.query(Role).count() > 0:
        # 已有数据时，更新新增的权限和字段（兼容已有数据库升级）
        _add_new_permissions(db)
        # [改进] 每次启动都校验用户角色完整性
        _validate_all_user_roles(db)
        # [改进] 同步有效角色名到 ORM 层校验器
        sync_valid_role_names(db)
        return

    # ==================== 权限定义 ====================
    permissions_data = [
        # 人员管理（实际可见范围受科室范围和工种范围双重限制）
        ("staff.view", "查看人员信息", "staff", "查看人员列表和详情（实际范围受科室/工种限制）"),
        ("staff.create", "新增人员", "staff", "新增人员信息（仅限管辖科室）"),
        ("staff.edit", "修改人员信息", "staff", "修改人员信息（仅限管辖科室内人员）"),
        ("staff.delete", "删除人员", "staff", "删除人员信息"),
        ("staff.status", "修改人员状态", "staff", "修改人员在职/离职状态（仅限管辖科室）"),
        # [新增 2026-09-11] 人员信息变更审核（立即生效 + 追认/回滚）
        ("staff.approve", "审核人员信息变更", "staff",
         "审核人员信息修改（科室管理员仅限管辖科室的科室级变更；超管审全部）"),
        # [新增 2026-09-15] 照片上传：控制能否上传人员形象照（正面/侧面）
        # 本人上传自己的照片始终允许（上传接口单独放行，无需本权限）；为他人上传需本权限 + 科室/工种数据范围
        ("staff.photo_upload", "照片上传", "staff",
         "上传人员照片（正面/侧面形象照）。本人可上传自己的照片；为他人上传受科室/工种数据范围限制；科室管理员默认拥有"),
        # [新增 2026-09-15] 修改历史（人员）：人员详情页「修改历史」入口与 /api/audit/history 接口访问；
        # 默认仅超级管理员拥有（不列入下方 role_default_perms 无条件补齐表，可自由授予/回收）
        ("staff.view_history", "修改历史", "staff", "查看人员详情页的最近三次修改记录（字段级修改前后对比）"),
        # 科室管理
        ("department.view", "查看科室信息", "department", "查看科室列表和详情（实际范围受科室限制）"),
        ("department.create", "新增科室", "department", "新增科室"),
        ("department.edit", "修改科室信息", "department", "修改科室信息（仅限管辖科室）"),
        ("department.delete", "删除科室", "department", "删除科室"),
        # [新增 2026-09-15] 修改历史（科室）：科室详情页「修改历史」入口与接口访问；默认仅超级管理员拥有
        ("department.view_history", "修改历史", "department", "查看科室详情页的最近三次修改记录（字段级修改前后对比）"),
        # 制度管理
        ("regulation.view", "查看制度", "regulation", "查看制度列表和详情"),
        ("regulation.create", "新增制度", "regulation", "新增制度"),
        ("regulation.edit", "编辑制度", "regulation", "编辑修改制度"),
        ("regulation.delete", "删除制度", "regulation", "删除制度"),
        # [修复 2026-09-07] 标识权限细化：拆分为「标识平面」与「标识设置」两大分类
        # 标识平面（workspace）
        ("signage.view", "查看标识", "signage_workspace", "查看标识列表和详情（标识管理/标记/预警/巡检页面访问基础）"),
        ("signage.create", "新增标识", "signage_workspace", "新增标识记录"),
        ("signage.edit", "编辑标识", "signage_workspace", "修改标识信息和状态"),
        ("signage.delete", "删除标识", "signage_workspace", "删除标识记录"),
        ("signage.marker", "标识标记", "signage_workspace", "在平面图上新增/删除标识点位"),
        ("signage.alert", "查看标识预警", "signage_workspace", "查看标识预警（状态异常/巡检到期/超期/有效期）"),
        ("signage.inspection", "标识巡检", "signage_workspace", "提交巡检结果与现场照片"),
        ("signage.export", "标识导入导出", "signage_workspace", "导出标识台账/附件压缩包，批量导入标识"),
        ("signage.repair", "查看维修记录", "signage_workspace", "查看全部标识维修记录并按条件导出"),
        # 标识设置（settings）
        ("signage.floorplan", "平面设置", "signage_settings", "管理平面图底图（新增/删除/上传图片）"),
        ("signage.campus", "院区管理", "signage_settings", "维护院区/楼栋/楼层/区域数据"),
        ("signage.category", "标识分类设置", "signage_settings", "维护标识分类（名称/编码/颜色/形状/巡检周期）"),
        ("signage.supplier", "供应商设置", "signage_settings", "维护供应商信息"),
        # 用户管理
        ("user.view", "查看用户", "user", "查看用户列表"),
        ("user.create", "新增用户", "user", "新增用户账号"),
        ("user.edit", "修改用户", "user", "修改用户信息"),
        ("user.delete", "删除用户", "user", "删除用户账号"),
        ("user.reset_password", "重置密码", "user", "重置用户密码"),
        # [新增 2026-09-10] 账号审核（登录页自助注册申请的通过/驳回）
        ("user.approve", "账号审核", "user", "审核登录页自助注册申请（仅限管辖科室）"),
        # 角色管理
        ("role.view", "查看角色", "role", "查看角色列表"),
        ("role.create", "新增角色", "role", "新增自定义角色"),
        ("role.edit", "修改角色", "role", "修改角色信息和权限"),
        ("role.delete", "删除角色", "role", "删除自定义角色"),
        # 数据管理
        ("data.export", "数据导出", "data", "导出数据到Excel（受科室/工种范围限制）"),
        ("data.import", "数据导入", "data", "从Excel导入数据"),
        # 系统管理
        ("system.config", "系统配置", "system", "修改系统配置参数"),
        ("system.backup", "数据备份", "system", "手动备份数据库"),
        ("system.audit", "审计日志", "system", "查看操作审计日志"),
        # 特殊功能
        ("card.upload", "上传工卡照片", "card", "上传医护人员的工卡照片"),
        # 人员管理 - 离职人员查看（归入人员管理分类）
        ("staff.view_resigned", "查看离职人员", "staff", "查看已离职人员（实际范围受科室/工种限制）"),
        # [新增 2026-09-11] 站内信（查看人人都有；私发/群发仅超级管理员）
        ("message.view", "查看站内信", "message", "查看本人站内信（收件箱/发件箱/标注）"),
        ("message.send", "发送站内信", "message", "向指定人员私发站内信"),
        ("message.broadcast", "群发站内信", "message", "按全员/科室/角色/权限群发站内信"),
        # [新增 2026-09-14] 功能开关权限点：与「系统设置 → 功能开关」构成两层控制——
        # 开关管单位级启停，本权限点管角色级访问。
        # [调整 2026-09-14] 原按功能拆分的 feature.messages / feature.signage / feature.regulation
        # 已合并为本单一权限点（需求：所有功能开关权限合并为一个权限，命名为「功能开关」）。
        # 功能内部的具体操作仍由原有细粒度权限（message.send / signage.create 等）控制。
        ("feature.access", "功能开关", "feature",
         "是否可访问受「功能开关」管控的功能（站内信、标识平面与标识设置、制度牌）"),
        # [新增 2026-09-15] 通知设置权限点：控制「系统设置 → 通知设置」的访问
        # （事件级开关 / 文案模板 / 收件人范围）。归入同一「系统设置」分类，
        # 与「功能开关」构成该分类下的两个权限项。
        ("feature.notification", "通知设置", "feature",
         "是否可访问「系统设置 → 通知设置」（配置系统站内信的开关、文案与收件人）"),
    ]

    perm_map = {}
    for name, display_name, category, description in permissions_data:
        p = Permission(name=name, display_name=display_name, category=category, description=description)
        db.add(p)
        db.flush()
        perm_map[name] = p

    all_perms = list(perm_map.values())

    # ==================== 预设角色（3个） ====================

    # 超级管理员 — 拥有系统全部管理权限（替代旧 super_admin）
    admin_manager = Role(
        name="admin_manager", display_name="超级管理员",
        description="拥有系统全部管理权限",
        is_system=True, department_scope="all", work_type_scope="all",
    )
    admin_manager.permissions = all_perms
    db.add(admin_manager)

    # 科室管理员 — 管理管辖科室的所有工种人员
    dept_manager = Role(
        name="dept_manager", display_name="科室管理员",
        description="管理管辖科室的所有人员，编辑管辖科室介绍。支持多科室管理",
        is_system=True, department_scope="managed", work_type_scope="all",
    )
    # [改进] 科室管理员不需要数据导出和上传工卡照片权限
    # [调整 2026-09-15] 默认权限收窄（需求）：科室管理员不再默认拥有
    #   照片上传、修改历史（人员 / 科室）、查看离职人员、修改人员状态、
    #   新增标识、编辑标识、标识标记、查看标识预警、标识导入导出、查看维修记录、
    #   功能开关、标识设置的所有权限（院区管理 / 平面设置 / 标识分类 / 供应商设置）。
    #   其中除「修改历史」外的权限同时列入下方第 4 段「科室管理员禁止集合」，
    #   每次启动强制移除（含存量库中已被历史版本授予的部分）。
    dept_manager.permissions = [
        perm_map["staff.view"], perm_map["staff.create"], perm_map["staff.edit"],
        # [新增 2026-09-11] 审核本科室人员的科室级信息变更
        perm_map["staff.approve"],
        perm_map["department.view"], perm_map["department.edit"],
        perm_map["regulation.view"],
        # [调整 2026-09-15] 保留「查看标识」与「标识巡检」两种基础能力，其余标识权限收回
        perm_map["signage.view"], perm_map["signage.inspection"],
        # [新增 2026-09-10] 账号审核（本科室注册申请）
        perm_map["user.approve"],
        # [新增 2026-09-11] 站内信查看（私发/群发仅超管）
        perm_map["message.view"],
    ]
    db.add(dept_manager)

    # 普通员工 — 查看本科室人员，可查看所有科室介绍
    employee = Role(
        name="employee", display_name="普通员工",
        description="查看本科室人员信息和所有科室介绍，可修改个人资料",
        is_system=True, department_scope="own", work_type_scope="all",
    )
    # [调整 2026-09-15] 默认权限调整（需求）：普通员工不再默认拥有
    #   查看标识预警（signage.alert）、查看维修记录（signage.repair）、功能开关（feature.access）；
    #   并新增「标识巡检」（signage.inspection），以支撑移动端扫码巡检。
    employee.permissions = [
        perm_map["staff.view"],
        perm_map["department.view"],
        perm_map["regulation.view"],
        perm_map["signage.view"],
        # [新增 2026-09-15] 标识巡检：普通员工可提交巡检结果与现场照片
        perm_map["signage.inspection"],
        # [新增 2026-09-11] 站内信查看
        perm_map["message.view"],
    ]
    db.add(employee)

    db.flush()
    logger.info("默认角色和权限初始化完成（3个预设角色）")

    # [改进] 首次初始化后同样执行完整性校验
    _validate_all_user_roles(db)
    sync_valid_role_names(db)


def _add_new_permissions(db: Session):
    """增量添加新增的权限和字段到已有数据库（兼容升级）"""
    # 1. 添加新版权限
    new_perms = [
        # 统一人员管理权限
        ("staff.view", "查看人员信息", "staff", "查看人员列表和详情（实际范围受科室/工种限制）"),
        ("staff.create", "新增人员", "staff", "新增人员信息（仅限管辖科室）"),
        ("staff.edit", "修改人员信息", "staff", "修改人员信息（仅限管辖科室内人员）"),
        ("staff.delete", "删除人员", "staff", "删除人员信息"),
        ("staff.status", "修改人员状态", "staff", "修改人员在职/离职状态（仅限管辖科室）"),
        # [新增 2026-09-11] 人员信息变更审核（存量库增量补齐）
        ("staff.approve", "审核人员信息变更", "staff",
         "审核人员信息修改（科室管理员仅限管辖科室的科室级变更；超管审全部）"),
        # [新增 2026-09-15] 照片上传（存量库增量补齐）；存量角色的授权回填见下方 1.9 段
        ("staff.photo_upload", "照片上传", "staff",
         "上传人员照片（正面/侧面形象照）。本人可上传自己的照片；为他人上传受科室/工种数据范围限制；科室管理员默认拥有"),
        ("staff.view_resigned", "查看离职人员", "staff", "查看已离职人员（实际范围受科室/工种限制）"),
        # [新增 2026-09-15] 修改历史（人员 / 科室，存量库增量补齐）；
        # 默认仅超级管理员拥有：超管由下方第 2 段「补充所有缺失权限」自动获得，
        # 刻意不对存量角色做回填（本能力为新增追溯权限，不随旧权限扩大范围）
        ("staff.view_history", "修改历史", "staff", "查看人员详情页的最近三次修改记录（字段级修改前后对比）"),
        ("department.view_history", "修改历史", "department", "查看科室详情页的最近三次修改记录（字段级修改前后对比）"),
        # 数据管理
        ("data.export", "数据导出", "data", "导出数据到Excel（受科室/工种范围限制）"),
        ("data.import", "数据导入", "data", "从Excel导入数据"),
        # 系统管理
        ("system.config", "系统配置", "system", "修改系统配置参数"),
        ("system.backup", "数据备份", "system", "手动备份数据库"),
        ("system.audit", "审计日志", "system", "查看操作审计日志"),
        # 特殊功能
        ("card.upload", "上传工卡照片", "card", "上传医护人员的工卡照片"),
        # [新增 2026-09-11] 站内信（存量库增量补齐）
        ("message.view", "查看站内信", "message", "查看本人站内信（收件箱/发件箱/标注）"),
        ("message.send", "发送站内信", "message", "向指定人员私发站内信"),
        ("message.broadcast", "群发站内信", "message", "按全员/科室/角色/权限群发站内信"),
        # [新增 2026-09-14] 功能级权限点（存量库增量补齐）
        # [调整 2026-09-14] 三个功能级权限点已合并为单一「功能开关」权限
        ("feature.access", "功能开关", "feature",
         "是否可访问受「功能开关」管控的功能（站内信、标识平面与标识设置、制度牌）"),
        # [新增 2026-09-15] 通知设置权限点（存量库增量补齐）；
        # 存量角色的授权回填见下方 1.8 段
        ("feature.notification", "通知设置", "feature",
         "是否可访问「系统设置 → 通知设置」（配置系统站内信的开关、文案与收件人）"),
        # 统一科室管理（如有缺失）
        ("department.create", "新增科室", "department", "新增科室"),
        ("department.delete", "删除科室", "department", "删除科室"),
        # 制度管理（如有缺失）
        ("regulation.view", "查看制度", "regulation", "查看制度列表和详情"),
        ("regulation.create", "新增制度", "regulation", "新增制度"),
        ("regulation.edit", "编辑制度", "regulation", "编辑修改制度"),
        ("regulation.delete", "删除制度", "regulation", "删除制度"),
        # [修复 2026-09-07] 标识权限细化：两大分类下的细粒度权限（存量库增量补齐）
        ("signage.view", "查看标识", "signage_workspace", "查看标识列表和详情（标识管理/标记/预警/巡检页面访问基础）"),
        ("signage.create", "新增标识", "signage_workspace", "新增标识记录"),
        ("signage.edit", "编辑标识", "signage_workspace", "修改标识信息和状态"),
        ("signage.delete", "删除标识", "signage_workspace", "删除标识记录"),
        ("signage.marker", "标识标记", "signage_workspace", "在平面图上新增/删除标识点位"),
        ("signage.alert", "查看标识预警", "signage_workspace", "查看标识预警（状态异常/巡检到期/超期/有效期）"),
        ("signage.inspection", "标识巡检", "signage_workspace", "提交巡检结果与现场照片"),
        ("signage.export", "标识导入导出", "signage_workspace", "导出标识台账/附件压缩包，批量导入标识"),
        ("signage.repair", "查看维修记录", "signage_workspace", "查看全部标识维修记录并按条件导出"),
        ("signage.floorplan", "平面设置", "signage_settings", "管理平面图底图（新增/删除/上传图片）"),
        ("signage.campus", "院区管理", "signage_settings", "维护院区/楼栋/楼层/区域数据"),
        ("signage.category", "标识分类设置", "signage_settings", "维护标识分类（名称/编码/颜色/形状/巡检周期）"),
        ("signage.supplier", "供应商设置", "signage_settings", "维护供应商信息"),
        # 用户管理（如有缺失）
        ("user.view", "查看用户", "user", "查看用户列表"),
        ("user.create", "新增用户", "user", "新增用户账号"),
        ("user.edit", "修改用户", "user", "修改用户信息"),
        ("user.delete", "删除用户", "user", "删除用户账号"),
        ("user.reset_password", "重置密码", "user", "重置用户密码"),
        # [新增 2026-09-10] 账号审核（存量库增量补齐）
        ("user.approve", "账号审核", "user", "审核登录页自助注册申请（仅限管辖科室）"),
        # 角色管理（如有缺失）
        ("role.view", "查看角色", "role", "查看角色列表"),
        ("role.create", "新增角色", "role", "新增自定义角色"),
        ("role.edit", "修改角色", "role", "修改角色信息和权限"),
        ("role.delete", "删除角色", "role", "删除自定义角色"),
        # 科室管理（如有缺失）
        ("department.view", "查看科室信息", "department", "查看科室列表和详情（实际范围受科室限制）"),
        ("department.edit", "修改科室信息", "department", "修改科室信息（仅限管辖科室）"),
    ]

    perm_map = {}
    for name, display_name, category, description in new_perms:
        existing = db.query(Permission).filter(Permission.name == name).first()
        if not existing:
            p = Permission(name=name, display_name=display_name, category=category, description=description)
            db.add(p)
            db.flush()
            perm_map[name] = p
            logger.info(f"新增权限: {name}")

    # 1.5 [修复 2026-09-07] 存量分类迁移：旧 signage 分类按新口径拆分到「标识平面/标识设置」
    legacy_category_map = {
        "signage.view": "signage_workspace",
        "signage.create": "signage_workspace",
        "signage.edit": "signage_workspace",
        "signage.delete": "signage_workspace",
        "signage.export": "signage_workspace",
        "signage.floorplan": "signage_settings",
    }
    migrated = 0
    for pname, new_cat in legacy_category_map.items():
        row = db.query(Permission).filter(Permission.name == pname, Permission.category == "signage").first()
        if row:
            row.category = new_cat
            migrated += 1
    if migrated:
        logger.info(f"已迁移 {migrated} 个存量标识权限到新分类（标识平面/标识设置）")

    # 1.6 [修复 2026-09-07] 细粒度权限的能力迁移：按旧权限自动授予新权限，保证存量角色升级后能力不缩水
    #  - 有 signage.view        → 授 signage.alert（预警页面原以 view 门禁）
    #  - 有 signage.edit        → 授 signage.inspection（巡检提交原要求 edit）、signage.marker
    #  - 有 signage.floorplan   → 授 signage.marker
    #  - 有 signage.create/edit/delete → 授 signage.category / signage.supplier（分类与供应商原用 CRUD 权限）
    #  [调整 2026-09-15] 原「有 department.create/edit/delete 任一 → 授 signage.campus」规则已移除：
    #  院区管理已纳入科室管理员禁止集合（dept_manager 必被收回），该规则对预设角色已无正向意义，
    #  却会把「院区管理」误授予自定义角色（doctor_admin / bread_admin / nurse_admin）。
    all_roles = db.query(Role).all()
    for role in all_roles:
        owned = {p.name for p in role.permissions}
        to_grant: set[str] = set()
        if "signage.view" in owned:
            to_grant.add("signage.alert")
        # [新增 2026-09-09] 维修记录权限补授：凡有预警权限的角色均可查看全部维修记录
        if "signage.alert" in owned:
            to_grant.add("signage.repair")
        if "signage.edit" in owned or "signage.floorplan" in owned:
            to_grant.add("signage.marker")
        if "signage.edit" in owned:
            to_grant.add("signage.inspection")
        if owned & {"signage.create", "signage.edit", "signage.delete"}:
            to_grant.update({"signage.category", "signage.supplier"})
        # [调整 2026-09-15] 不再自动授予 signage.campus（原因见上方说明）
        granted = 0
        for pname in to_grant:
            perm = db.query(Permission).filter(Permission.name == pname).first()
            if perm and perm not in role.permissions:
                role.permissions.append(perm)
                granted += 1
        if granted:
            logger.info(f"已为角色 {role.name} 迁移授予 {granted} 个细粒度标识权限")

    # 1.7 [调整 2026-09-14] 功能开关权限点：合并为单一 feature.access
    #
    # 背景：此前按功能拆分为 feature.messages / feature.signage / feature.regulation 三个权限点，
    # 现按需求合并为一个「功能开关」权限。本段完成：
    #   a) [调整 2026-09-15] **取消存量回填**——原先按「已有哪些细粒度权限」把 feature.access
    #      回填给所有相关角色，但 ① 模块菜单门禁已改为细粒度权限（frontend/Layout.tsx），
    #      feature.access 不再决定菜单可见性；② 该权限的默认范围已收窄为「仅超级管理员」。
    #      继续回填只会把「功能开关」误授予自定义角色（如 doctor_admin / Hosp_leader）。
    #      超管由下方第 2 段统一补齐，不依赖本回填。
    #   b) 合并迁移——把三个旧功能权限的持有关系折算到新权限，并**删除旧权限本身**，
    #      否则「角色管理」里会残留已废弃的勾选项，与"合并为一个权限"的预期不符。
    FEATURE_ACCESS_NAME = "feature.access"
    LEGACY_FEATURE_NAMES = ("feature.messages", "feature.signage", "feature.regulation")

    access_perm = db.query(Permission).filter(Permission.name == FEATURE_ACCESS_NAME).first()
    legacy_perms = db.query(Permission).filter(Permission.name.in_(LEGACY_FEATURE_NAMES)).all()

    # b) 合并迁移：旧功能权限的持有者折算为拥有新权限，随后移除关联并删除旧权限
    if legacy_perms and access_perm:
        legacy_ids = {p.id for p in legacy_perms}
        migrated = 0
        for role in db.query(Role).all():
            owned_ids = {p.id for p in role.permissions}
            if not (owned_ids & legacy_ids):
                continue
            if access_perm not in role.permissions:
                role.permissions.append(access_perm)
            # 摘除旧功能权限（保留该角色其余权限不变）
            role.permissions = [p for p in role.permissions if p.id not in legacy_ids]
            migrated += 1
        # 先落盘关联表删除，再删除权限本身，避免残留悬空关联
        db.flush()
        for p in legacy_perms:
            db.delete(p)
        db.flush()
        logger.info(
            f"功能开关权限已合并：删除 {len(legacy_perms)} 个旧权限点，{migrated} 个角色完成迁移"
        )

    # 1.8 [新增 2026-09-15] 通知设置权限点：新增独立权限 feature.notification
    #
    # 背景：通知设置（系统设置 → 通知设置）此前复用 system.config，与「功能开关」共用同一门槛，
    # 无法按角色单独授权。现按需求在角色管理中新增独立权限项「通知设置」（分类「系统设置」）。
    #
    # a) 存量回填——新权限"本次新建"时，凡已拥有 system.config 的角色（即改造前本就能访问
    #    通知设置页的角色）一并授予，保证升级后访问范围不缩水；仅执行一次，
    #    此后管理员在「角色管理」中取消不会被下次重启覆盖（故 feature.notification
    #    刻意不写入下方 role_default_perms 的无条件补齐表）。
    NOTIFY_PERM_NAME = "feature.notification"
    notify_perm = db.query(Permission).filter(Permission.name == NOTIFY_PERM_NAME).first()
    if notify_perm and NOTIFY_PERM_NAME in perm_map:
        backfilled = 0
        for role in db.query(Role).all():
            owned = {p.name for p in role.permissions}
            if "system.config" in owned and notify_perm not in role.permissions:
                role.permissions.append(notify_perm)
                backfilled += 1
        if backfilled:
            logger.info(f"已为 {backfilled} 个存量角色回填通知设置权限: {NOTIFY_PERM_NAME}")

    # 2. 给 admin_manager 角色补充所有缺失权限（确保拥有全部权限）
    # 1.9 [新增 2026-09-15] 照片上传权限点：新增独立权限 staff.photo_upload
    #
    # 背景：人员形象照（正面/侧面）上传此前与「修改人员信息」（staff.edit）共用同一门禁，
    # 无法按角色单独授予/回收。现按需求在「角色管理 → 人员管理」中新增独立权限项「照片上传」。
    #
    # a) 存量回填——新权限首次创建时，凡已拥有 staff.edit 的角色（即改造前本就能为他人
    #    上传照片的角色）一并授予，保证升级后能力不缩水；仅执行一次，此后管理员在「角色管理」
    #    中取消不会被下次重启覆盖（故刻意不写入下方 role_default_perms 的无条件补齐表）。
    #    本人上传自己的照片不受本权限限制（上传接口单独放行），故普通员工无需该权限。
    PHOTO_UPLOAD_PERM_NAME = "staff.photo_upload"
    photo_upload_perm = db.query(Permission).filter(Permission.name == PHOTO_UPLOAD_PERM_NAME).first()
    if photo_upload_perm and PHOTO_UPLOAD_PERM_NAME in perm_map:
        backfilled = 0
        for role in db.query(Role).all():
            owned = {p.name for p in role.permissions}
            if "staff.edit" in owned and photo_upload_perm not in role.permissions:
                role.permissions.append(photo_upload_perm)
                backfilled += 1
        if backfilled:
            logger.info(f"已为 {backfilled} 个存量角色回填照片上传权限: {PHOTO_UPLOAD_PERM_NAME}")

    # 1.10 [新增 2026-09-15] 废弃科室权限清理：department.create_clinic / create_ward /
    #      delete_clinic / delete_ward 是「统一科室管理」改造前的旧权限点
    #      （新增/删除科室现由 department.create / department.delete 承载）。
    #      新代码不再定义它们，但历史库仍残留权限行与角色关联，导致：
    #        - 「角色管理 → 科室管理」分组显示 9 项（应为 5 项）；
    #        - dept_manager 通过默认表被补回 create_clinic / create_ward。
    #      本段对**所有角色**摘除关联后删除权限行（幂等，仅在有残留时执行）；
    #      必须位于第 2 段「超管补齐全部权限」之前，避免清理前又被补回。
    LEGACY_DEPT_PERMS = (
        "department.create_clinic", "department.create_ward",
        "department.delete_clinic", "department.delete_ward",
    )
    legacy_dept_rows = db.query(Permission).filter(Permission.name.in_(LEGACY_DEPT_PERMS)).all()
    if legacy_dept_rows:
        legacy_dept_ids = {p.id for p in legacy_dept_rows}
        detached = 0
        for role in db.query(Role).all():
            if {p.id for p in role.permissions} & legacy_dept_ids:
                role.permissions = [p for p in role.permissions if p.id not in legacy_dept_ids]
                detached += 1
        db.flush()  # 先落盘关联表删除，避免悬空引用
        removed_names = [p.name for p in legacy_dept_rows]
        for p in legacy_dept_rows:
            db.delete(p)
        db.flush()
        logger.info(f"已清理 {len(removed_names)} 个废弃科室权限（涉及 {detached} 个角色）: {removed_names}")

    admin_role = db.query(Role).filter(Role.name == "admin_manager").first()
    if admin_role:
        all_perms = db.query(Permission).all()
        added_count = 0
        for p in all_perms:
            if p not in admin_role.permissions:
                admin_role.permissions.append(p)
                added_count += 1
        if added_count > 0:
            logger.info(f"已为 admin_manager 补充 {added_count} 个缺失权限")

    # 2.5 更新预设角色的权限（补充缺失权限）
    role_default_perms = {
        # [改进] 科室管理员不再具有数据导出、上传工卡照片、删除临床专科、删除护理病区权限
        # [修复 2026-09-07] 补充标识细粒度权限（预警/巡检/标记/分类/供应商/院区），保持升级后能力不缩水
        "dept_manager": [
            # [调整 2026-09-15] 默认权限收窄（需求）：本表只保留科室管理员的常规能力。
            # 「照片上传 / 修改历史 / 查看离职人员 / 修改人员状态 / 标识新增·编辑·标记·预警·
            # 导入导出·维修记录 / 功能开关 / 标识设置（院区·平面·分类·供应商）」均已从本表移除，
            # 并（除修改历史外）列入下方第 4 段「科室管理员禁止集合」，每次启动强制移除。
            "staff.view", "staff.create", "staff.edit",
            # [新增 2026-09-11] 审核本科室人员的科室级信息变更
            "staff.approve",
            "department.view", "department.edit",
            # [调整 2026-09-15] 已废弃的 department.create_clinic / create_ward 移出本表
            # （权限点本身由上方 1.10 段统一清理，避免每次启动再被补回）
            "regulation.view",
            # [调整 2026-09-15] 保留查看标识与标识巡检；其余标识能力已收回（见上）
            "signage.view", "signage.inspection",
            # [新增 2026-09-10] 科室管理员可审核本科室的注册申请
            "user.approve",
            # [新增 2026-09-11] 站内信查看（私发/群发仅超管）
            "message.view",
        ],
        "employee": [
            # [调整 2026-09-15] 默认权限调整（需求）：移除「查看标识预警」「查看维修记录」
            # （功能开关 feature.access 本就不在本表内），新增「标识巡检」。
            "staff.view", "department.view", "regulation.view",
            "signage.view",
            "signage.inspection",
            # [新增 2026-09-11] 站内信查看
            "message.view",
        ],
    }
    for role_name, perm_names in role_default_perms.items():
        role = db.query(Role).filter(Role.name == role_name).first()
        if role:
            added = 0
            for pname in perm_names:
                perm = db.query(Permission).filter(Permission.name == pname).first()
                if perm and perm not in role.permissions:
                    role.permissions.append(perm)
                    added += 1
            if added > 0:
                logger.info(f"已为 {role_name} 角色补充 {added} 个缺失权限")

    # 3. 用户角色完整性校验已提升到 init_default_roles() 每次启动都执行，
    #    不再仅依赖增量权限升级时的修复逻辑。见 _validate_all_user_roles()。

    # 4. [改进] 从科室管理员角色移除数据导出、上传工卡照片、删除临床专科、删除护理病区权限
    #    [调整 2026-09-15] 默认权限收窄（需求）：科室管理员不再拥有以下权限，
    #    统一并入本禁止集合，每次启动强制移除（含存量库中已被历史版本授予的部分）：
    #      照片上传 / 查看离职人员 / 修改人员状态；
    #      新增标识 / 编辑标识 / 标识标记 / 查看标识预警 / 标识导入导出 / 查看维修记录；
    #      功能开关；标识设置全部权限（院区管理 / 平面设置 / 标识分类 / 供应商设置）。
    #    说明：本集合为「硬性禁止」（与既有 card.upload / data.export 的处理方式一致），
    #    如需放开某个权限，请从本集合中移除对应权限名。
    #    「修改历史」（staff.view_history / department.view_history）不在本集合内：
    #    其定位为「默认仅超管、可在角色管理中授予/回收」，故仅不出现在默认表。
    dept_role = db.query(Role).filter(Role.name == "dept_manager").first()
    if dept_role:
        removed_count = 0
        perm_keys_to_remove = {
            "card.upload", "data.export", "department.delete_clinic", "department.delete_ward",
            # [新增 2026-09-15] 科室管理员默认权限收窄
            "staff.status", "staff.photo_upload", "staff.view_resigned",
            "signage.create", "signage.edit", "signage.marker", "signage.alert",
            "signage.export", "signage.repair",
            "signage.floorplan", "signage.campus", "signage.category", "signage.supplier",
            "feature.access",
        }
        for pname in perm_keys_to_remove:
            perm = db.query(Permission).filter(Permission.name == pname).first()
            if perm and perm in dept_role.permissions:
                dept_role.permissions.remove(perm)
                removed_count += 1
        if removed_count > 0:
            logger.info(f"已从 dept_manager 角色移除 {removed_count} 个权限: {perm_keys_to_remove}")

    # 4.1 [新增 2026-09-15] 普通员工默认权限调整（需求）：
    #     移除「查看标识预警」「查看维修记录」「功能开关」，新增「标识巡检」（由上方 2.5 段默认表补齐）。
    #     与 dept_manager 处理方式一致：本集合为「硬性禁止」，每次启动强制移除，
    #     确保存量库中已被历史版本授予的这些权限被一并收回。
    emp_role = db.query(Role).filter(Role.name == "employee").first()
    if emp_role:
        emp_removed = 0
        emp_keys_to_remove = {"signage.alert", "signage.repair", "feature.access"}
        for pname in emp_keys_to_remove:
            perm = db.query(Permission).filter(Permission.name == pname).first()
            if perm and perm in emp_role.permissions:
                emp_role.permissions.remove(perm)
                emp_removed += 1
        if emp_removed > 0:
            logger.info(f"已从 employee 角色移除 {emp_removed} 个权限: {emp_keys_to_remove}")

    # 5. 更新已有角色的 department_scope 和 work_type_scope（仅当字段为空/NULL时设置默认值，保护管理员UI修改）
    scope_mapping = {
        "admin_manager": ("all", "all"),
        "dept_manager": ("managed", "all"),
        "employee": ("own", "all"),
    }

    for role_name, (dept_scope, work_scope) in scope_mapping.items():
        role = db.query(Role).filter(Role.name == role_name).first()
        if role:
            # 仅当字段为空时设置默认值，避免覆盖管理员通过UI修改的配置
            if not role.department_scope:
                role.department_scope = dept_scope
                logger.info(f"已设置角色 {role_name} 的 department_scope 默认值: {dept_scope}")
            if not role.work_type_scope:
                role.work_type_scope = work_scope
                logger.info(f"已设置角色 {role_name} 的 work_type_scope 默认值: {work_scope}")

    db.flush()


# ==================== 用户角色完整性校验（每次启动执行） ====================

# 旧版角色名 → 正确角色名映射
_LEGACY_ROLE_MAP = {
    "admin": "admin_manager",
    "super_admin": "admin_manager",
    "department_head": "dept_manager",
}


def _validate_all_user_roles(db: Session):
    """[改进] 每次启动校验所有用户的 role 字段，自动修正脏数据。
    
    当用户 role 字段值与 roles 表不匹配时，user.role_obj 为 None，
    has_permission() 始终返回 False，用户失去所有权限。
    此函数在每次启动时扫描并修正，作为数据库层面的最后保障。
    """
    from app.models.user import User as UserModel

    # 获取所有有效角色名
    valid_role_names = {r.name for r in db.query(Role).all()}
    if not valid_role_names:
        logger.warning("角色表为空，跳过用户角色校验")
        return

    all_users = db.query(UserModel).all()
    fixed_count = 0
    orphan_count = 0

    for u in all_users:
        if u.role not in valid_role_names:
            # 检查是否为已知旧版值
            if u.role in _LEGACY_ROLE_MAP:
                corrected = _LEGACY_ROLE_MAP[u.role]
                logger.warning(
                    "启动时自动修正用户角色: employee_id=%s, '%s' → '%s'",
                    u.employee_id, u.role, corrected,
                )
                u.role = corrected
                correct_role = db.query(Role).filter(Role.name == corrected).first()
                if correct_role:
                    u.role_id = correct_role.id
                fixed_count += 1
            else:
                # 既不是有效值也不是已知旧版值 — 发出警告但保持原样
                logger.error(
                    "发现孤立角色名: employee_id=%s, role='%s'（不在 roles 表中）",
                    u.employee_id, u.role,
                )
                orphan_count += 1

    if fixed_count > 0:
        db.flush()
        logger.info("已自动修正 %d 个用户的角色名", fixed_count)
    if orphan_count > 0:
        logger.error(
            "发现 %d 个用户使用了数据库中不存在的角色名，这些用户将没有任何权限！"
            "请立即通过管理界面修正这些用户的角色。", orphan_count,
        )


def sync_valid_role_names(db: Session) -> None:
    """[改进] 将当前有效角色名同步到 User 模型的 ORM 校验器（幂等、可重复调用）。
    
    这确保 @validates('role') 在 ORM 层拦截无效角色名写入。

    [修复 2026-09-10] 除启动时调用外，**角色新建/删除后也必须调用**
    （已在 role_service.create_role / delete_role 内自动调用），
    同时 user_service 在创建/修改用户前会再同步一次兜底。
    否则本次运行内新角色的名称不在校验集合中，给用户分配该角色会被
    @validates 误判为「无效角色名」，必须重启才生效。
    """
    from app.models.user import set_valid_role_names
    valid_names = {r.name for r in db.query(Role).all()}
    set_valid_role_names(valid_names)
    logger.info("已同步 %d 个有效角色名到 ORM 校验器: %s", len(valid_names), sorted(valid_names))
