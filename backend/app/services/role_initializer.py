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
        # 科室管理
        ("department.view", "查看科室信息", "department", "查看科室列表和详情（实际范围受科室限制）"),
        ("department.create", "新增科室", "department", "新增科室"),
        ("department.edit", "修改科室信息", "department", "修改科室信息（仅限管辖科室）"),
        ("department.delete", "删除科室", "department", "删除科室"),
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
    dept_manager.permissions = [
        perm_map["staff.view"], perm_map["staff.create"], perm_map["staff.edit"], perm_map["staff.status"],
        # [新增 2026-09-11] 审核本科室人员的科室级信息变更
        perm_map["staff.approve"],
        perm_map["department.view"], perm_map["department.edit"],
        perm_map["regulation.view"],
        perm_map["signage.view"], perm_map["signage.create"], perm_map["signage.edit"], perm_map["signage.export"],
        perm_map["signage.repair"],
        # [新增 2026-09-10] 账号审核（本科室注册申请）
        perm_map["user.approve"],
        # [新增 2026-09-11] 站内信查看（私发/群发仅超管）
        perm_map["message.view"],
        # [新增 2026-09-11] 查看离职人员：科室管理员需要看到本科室离职人员
        perm_map["staff.view_resigned"],
    ]
    db.add(dept_manager)

    # 普通员工 — 查看本科室人员，可查看所有科室介绍
    employee = Role(
        name="employee", display_name="普通员工",
        description="查看本科室人员信息和所有科室介绍，可修改个人资料",
        is_system=True, department_scope="own", work_type_scope="all",
    )
    employee.permissions = [
        perm_map["staff.view"],
        perm_map["department.view"],
        perm_map["regulation.view"],
        perm_map["signage.view"],
        perm_map["signage.repair"],
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
        ("staff.view_resigned", "查看离职人员", "staff", "查看已离职人员（实际范围受科室/工种限制）"),
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
    #  - 有 department.create/edit/delete 任一 → 授 signage.campus（院区管理原用科室权限）
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
        if owned & {"department.create", "department.edit", "department.delete"}:
            to_grant.add("signage.campus")
        granted = 0
        for pname in to_grant:
            perm = db.query(Permission).filter(Permission.name == pname).first()
            if perm and perm not in role.permissions:
                role.permissions.append(perm)
                granted += 1
        if granted:
            logger.info(f"已为角色 {role.name} 迁移授予 {granted} 个细粒度标识权限")

    # 2. 给 admin_manager 角色补充所有缺失权限（确保拥有全部权限）
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
            "staff.view", "staff.create", "staff.edit", "staff.status",
            # [新增 2026-09-11] 审核本科室人员的科室级信息变更
            "staff.approve",
            "department.view", "department.edit",
            "department.create_clinic", "department.create_ward",
            "regulation.view",
            "signage.view", "signage.create", "signage.edit", "signage.export",
            "signage.alert", "signage.inspection", "signage.marker",
            "signage.repair",
            "signage.category", "signage.supplier", "signage.campus",
            # [新增 2026-09-10] 科室管理员可审核本科室的注册申请
            "user.approve",
            # [新增 2026-09-11] 站内信查看（私发/群发仅超管）
            "message.view",
            # [新增 2026-09-11] 查看离职人员（本科室范围内的离职人员）
            "staff.view_resigned",
        ],
        "employee": [
            "staff.view", "department.view", "regulation.view",
            "signage.view", "signage.alert",
            "signage.repair",
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
    dept_role = db.query(Role).filter(Role.name == "dept_manager").first()
    if dept_role:
        removed_count = 0
        perm_keys_to_remove = {"card.upload", "data.export", "department.delete_clinic", "department.delete_ward"}
        for pname in perm_keys_to_remove:
            perm = db.query(Permission).filter(Permission.name == pname).first()
            if perm and perm in dept_role.permissions:
                dept_role.permissions.remove(perm)
                removed_count += 1
        if removed_count > 0:
            logger.info(f"已从 dept_manager 角色移除 {removed_count} 个权限: {perm_keys_to_remove}")

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
