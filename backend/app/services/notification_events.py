# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""通知事件注册表（系统设置 → 通知设置 的「可配置项」清单）

[新增 2026-09-15]
==================
本模块是通知中心（`notification_center.py`）的**默认值来源**：每个业务事件在此
登记一次，之后设置页与发送引擎都以此为口径。新增事件只需在此追加一条，
「通知设置」页会自动出现该项，前端无需改动。

每个事件的字段：
    code                     事件编码，全局唯一，规则表按它关联（不要随意改名）
    module                   设置页分组（人员管理 / 工卡管理 / 系统运维 ...）
    label                    事件名称
    description              一句话说明（设置页副标题）
    default_enabled          默认是否发送（升级后不配置即按此执行）
    default_recipients_mode  "modification" = 超管 + 相关科室管理员（排除操作者）
                             "explicit"     = 由业务调用点传入收件人
    default_recipient_hint   默认收件人范围的人话说明（设置页展示）
    default_title            默认标题模板（未配置时使用，即改造前的原文案）
    default_content          默认正文模板（支持 {变量} 与简单 HTML）
    variables                {变量名: 说明}，供设置页「可用变量」提示
    sample                   预览用示例值（设置页与「发送测试」使用）
    related_type             站内信关联业务类型（前端据此渲染跳转按钮）

[新增 2026-09-15] 两个可选字段（不写则按默认推断，见下方函数）：
    actor_fallback           收件人解析为空时，是否回落给「操作者本人」作为操作回执。
                             修改提醒类事件默认 True，解决「系统只有一个超管、且由该
                             超管操作」时收件人被排除成空集、改动无人知悉的问题。
    keep_actor               是否**不排除**操作者本人（默认 False）。
                             用于「本人操作需回执给本人」的场景，如个人账号安全设置变更。
"""

# 收件人解析预设
MODE_MODIFICATION = "modification"  # 超管 + 相关科室管理员（自动排除操作者本人）
MODE_EXPLICIT = "explicit"          # 业务调用点显式传入

# 事件分组展示顺序（设置页按此顺序展示分组；未登记的分组自动排到末尾）
MODULE_ORDER = [
    "人员管理", "科室管理", "照片管理", "工卡管理", "信息变更审核",
    "账号与权限", "标识管理", "制度与供应商", "院区与楼层", "系统配置",
    "数据管理", "系统运维",
]


NOTIFICATION_EVENTS: list[dict] = [
    # ==================== 人员管理 ====================
    {
        "code": "staff.updated",
        "module": "人员管理",
        "label": "人员信息被修改",
        "description": "人员档案被修改后通知管理方；已派发审核任务的改动由待审核通知承载，不重复发送。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "staff",
        "default_title": "人员信息被修改",
        "default_content": "{操作人} 修改了 {姓名}({工号}) 的{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "姓名": "被修改人员姓名",
            "工号": "被修改人员工号",
            "变更内容": "本次修改的字段摘要，如「职称、学历」",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101", "变更内容": "职称"},
    },
    {
        "code": "staff.intro_updated",
        "module": "人员管理",
        "label": "个人介绍被修改",
        "description": (
            "有编辑权限的人员（如科室管理员）修改他人的「个人介绍」类字段"
            "（备注 / 专业擅长 / 社会任职 / 荣誉）后，直接通知被修改人知悉；"
            "此类字段免审、不产生审核任务，改自己时不发送。"
        ),
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "被修改人本人",
        # 收件人为显式指定（被修改人），不存在「解析为空」的场景，故关闭兜底回落
        "actor_fallback": False,
        "related_type": "staff",
        "default_title": "您的个人介绍已被修改",
        "default_content": "{操作人} 修改了您的个人介绍（{姓名} · {工号}）：{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "姓名": "被修改人员姓名",
            "工号": "被修改人员工号",
            "变更内容": "本次修改的字段摘要（含修改前后值）",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "变更内容": "专业擅长（短）: 心血管内科 → 心血管内科、高血压"},
    },
    {
        "code": "staff.resigned",
        "module": "人员管理",
        "label": "人员离职提醒",
        "description": "人员被标记为离职（登录账号同时停用）后通知管理方。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "staff",
        "default_title": "人员离职提醒",
        "default_content": "{操作人} 已将 {姓名}（{工号} · {科室}）标记为离职{离职原因}；其登录账号已停用。",
        "variables": {
            "操作人": "执行操作的人员姓名",
            "姓名": "离职人员姓名",
            "工号": "离职人员工号",
            "科室": "离职人员所属科室",
            "离职原因": "已填原因时为「，原因：xxx」，未填时为空",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "科室": "心内科", "离职原因": "，原因：个人原因"},
    },
    {
        "code": "staff.restored",
        "module": "人员管理",
        "label": "人员复职提醒",
        "description": "人员由离职恢复为在职（登录账号同时恢复启用）后通知管理方。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "staff",
        "default_title": "人员复职提醒",
        "default_content": "{操作人} 已将 {姓名}（{工号} · {科室}）恢复为在职，登录账号已恢复启用。",
        "variables": {
            "操作人": "执行操作的人员姓名",
            "姓名": "复职人员姓名",
            "工号": "复职人员工号",
            "科室": "复职人员所属科室",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101", "科室": "心内科"},
    },
    {
        "code": "staff.created",
        "module": "人员管理",
        "label": "新增人员",
        "description": "人员档案被新增后通知管理方（新增档案此前无任何提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "staff",
        "default_title": "新增人员：{姓名}",
        "default_content": "{操作人} 新增了人员 {姓名}（{工号} · {科室} · {工种}）",
        "variables": {
            "操作人": "执行新增的人员姓名",
            "姓名": "新增人员姓名",
            "工号": "新增人员工号",
            "科室": "新增人员所属科室",
            "工种": "医生 / 护士 / 技师 / 行政",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "科室": "心内科", "工种": "医生"},
    },
    {
        "code": "staff.deleted",
        "module": "人员管理",
        "label": "删除人员",
        "description": "人员档案被删除后通知管理方（档案及其照片文件会一并清理，属高敏感操作）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "staff",
        "default_title": "删除人员：{姓名}",
        "default_content": "{操作人} 删除了人员 {姓名}（{工号} · {科室} · {工种}），其档案与照片文件已被清理。",
        "variables": {
            "操作人": "执行删除的人员姓名",
            "姓名": "被删除人员姓名",
            "工号": "被删除人员工号",
            "科室": "被删除人员所属科室",
            "工种": "医生 / 护士 / 技师 / 行政",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "科室": "心内科", "工种": "医生"},
    },
    # ==================== 科室管理 ====================
    {
        "code": "department.updated",
        "module": "科室管理",
        "label": "科室信息被修改",
        "description": "科室资料（名称、简介、专业组、设备等）被修改后通知管理方。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 该科室的相关科室管理员（自动排除操作者本人）",
        "related_type": "department",
        "default_title": "科室信息被修改",
        "default_content": "{操作人} 修改了科室 {科室}(ID:{科室ID}) 的{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "科室": "被修改的科室名称",
            "科室ID": "被修改的科室编号",
            "变更内容": "本次修改的字段摘要",
        },
        "sample": {"操作人": "张管理", "科室": "心内科", "科室ID": "3", "变更内容": "科室简介"},
    },
    {
        "code": "department.created",
        "module": "科室管理",
        "label": "新增科室",
        "description": "新建科室后通知管理方（此前无任何提醒与留痕）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "department",
        "default_title": "新增科室",
        "default_content": "{操作人} 新增了科室 {科室}(ID:{科室ID}) 的{变更内容}",
        "variables": {
            "操作人": "执行新增的人员姓名",
            "科室": "新增的科室名称",
            "科室ID": "新增的科室编号",
            "变更内容": "本次操作的摘要（含科室分类）",
        },
        "sample": {"操作人": "张管理", "科室": "心内科", "科室ID": "3", "变更内容": "新建科室(分类: 临床专科)"},
    },
    {
        "code": "department.deleted",
        "module": "科室管理",
        "label": "删除科室",
        "description": "删除科室后通知管理方（高敏感操作，此前无任何提醒与留痕）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "department",
        "default_title": "删除科室",
        "default_content": "{操作人} 删除了科室 {科室}(ID:{科室ID}) 的{变更内容}",
        "variables": {
            "操作人": "执行删除的人员姓名",
            "科室": "被删除的科室名称",
            "科室ID": "被删除的科室编号",
            "变更内容": "本次操作的摘要（含科室分类）",
        },
        "sample": {"操作人": "张管理", "科室": "心内科", "科室ID": "3", "变更内容": "删除科室(分类: 临床专科)"},
    },
    {
        "code": "department.photo_changed",
        "module": "科室管理",
        "label": "科室合照变更",
        "description": "科室合照被上传 / 替换 / 删除后通知管理方（此前无任何提醒与留痕）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "department",
        "default_title": "科室合照变更",
        "default_content": "{操作人} 修改了科室 {科室}(ID:{科室ID}) 的{变更内容}",
        "variables": {
            "操作人": "执行操作的人员姓名",
            "科室": "被修改的科室名称",
            "科室ID": "被修改的科室编号",
            "变更内容": "本次操作的摘要，如「科室合照: 旧图.png → 新图.png」或「科室合照(删除: 图.png)」",
        },
        "sample": {"操作人": "张管理", "科室": "心内科", "科室ID": "3",
                   "变更内容": "科室合照(上传: group_3_1.png)"},
    },
    {
        "code": "department.specialty_changed",
        "module": "科室管理",
        "label": "科室特色技术 / 设备图片变更",
        "description": "科室特色技术、设备的图片被新增 / 删除 / 改备注后通知管理方（此前无任何提醒与留痕）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "department",
        "default_title": "科室特色技术 / 设备变更",
        "default_content": "{操作人} 修改了科室 {科室}(ID:{科室ID}) 的{变更内容}",
        "variables": {
            "操作人": "执行操作的人员姓名",
            "科室": "被修改的科室名称",
            "科室ID": "被修改的科室编号",
            "变更内容": "本次操作的摘要，含特色技术/设备名称与操作类型",
        },
        "sample": {"操作人": "张管理", "科室": "心内科", "科室ID": "3",
                   "变更内容": "特色技术「冠脉介入」图片(新增1张)"},
    },
    # ==================== 照片管理 ====================
    {
        "code": "photo.updated",
        "module": "照片管理",
        "label": "人员照片更新",
        "description": "人员正面照 / 侧面照被他人更新后通知管理方；已派发审核任务时不重复发送。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "photo",
        "default_title": "{姓名}的照片已更新",
        "default_content": "{操作人} 更新了 {姓名}({工号}) 的{照片类型}",
        "variables": {
            "操作人": "执行上传的人员姓名",
            "姓名": "照片归属人员姓名",
            "工号": "照片归属人员工号",
            "照片类型": "「正面照」或「侧面照」",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101", "照片类型": "正面照"},
    },
    {
        "code": "photo.deleted",
        "module": "照片管理",
        "label": "人员照片删除",
        "description": "人员正面照 / 侧面照被他人删除后通知管理方。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "photo",
        "default_title": "{姓名}的照片被删除",
        "default_content": "{操作人} 删除了 {姓名}({工号}) 的{照片类型}",
        "variables": {
            "操作人": "执行删除的人员姓名",
            "姓名": "照片归属人员姓名",
            "工号": "照片归属人员工号",
            "照片类型": "「正面照」或「侧面照」",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101", "照片类型": "侧面照"},
    },
    # ==================== 工卡管理 ====================
    {
        "code": "card.uploaded",
        "module": "工卡管理",
        "label": "工卡上传待确认",
        "description": "工卡照片上传后，通知本人及有工卡上传权限的管理人员确认。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "卡片归属人本人 + 有「工卡上传」权限且数据范围覆盖该科室的人员",
        "related_type": "card",
        "default_title": "{姓名}的卡片需要确认",
        "default_content": "{姓名}（{工号}）上传了{人员类型}卡片，请及时确认。",
        "variables": {
            "姓名": "卡片归属人员姓名",
            "工号": "卡片归属人员工号",
            "人员类型": "医生 / 护士 / 技师 / 行政人员 / 人员",
        },
        "sample": {"姓名": "李医生", "工号": "060101", "人员类型": "医生"},
    },
    {
        "code": "card.confirmed",
        "module": "工卡管理",
        "label": "工卡已确认",
        "description": "工卡被确认后，通知卡片上传者。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "卡片上传者",
        "related_type": "card",
        "default_title": "{姓名}的卡片照已确认",
        "default_content": "{操作人} 确认了 {姓名}({工号}) 的卡片照",
        "variables": {
            "操作人": "执行确认的人员姓名",
            "姓名": "卡片归属人员姓名",
            "工号": "卡片归属人员工号",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101"},
    },
    {
        "code": "card.rejected",
        "module": "工卡管理",
        "label": "工卡被拒绝",
        "description": "工卡被拒绝后，通知卡片上传者。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "卡片上传者",
        "related_type": "card",
        "default_title": "{姓名}的卡片照被拒绝",
        "default_content": "{操作人} 拒绝了 {姓名}({工号}) 的卡片照{拒绝原因}",
        "variables": {
            "操作人": "执行拒绝的人员姓名",
            "姓名": "卡片归属人员姓名",
            "工号": "卡片归属人员工号",
            "拒绝原因": "已填原因时为「，原因：xxx」，未填时为空",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101", "拒绝原因": "，原因：照片不清晰"},
    },
    # ==================== 信息变更审核 ====================
    {
        "code": "staff_change.submitted",
        "module": "信息变更审核",
        "label": "信息变更待审核",
        "description": "人员信息变更提交后，通知对应级别的审核人（站内信含「去审核」入口）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "该变更对应级别的审核人（科室负责人 / 超级管理员）",
        "related_type": "staff_change",
        "default_title": "待审核：{姓名} 的信息变更",
        "default_content": (
            "{提交人} 提交了 {姓名}（{工号} · {科室}）的信息变更，需由{审核级别}审核：<br/>"
            "{变更内容}<br/><b>该变更已立即生效</b>，审核不通过将回滚为修改前的值。"
        ),
        "variables": {
            "提交人": "提交变更的人员姓名",
            "姓名": "被修改人员姓名",
            "工号": "被修改人员工号",
            "科室": "被修改人员所属科室",
            "审核级别": "「科室负责人」或「超级管理员」",
            "变更内容": "本次变更的字段摘要",
        },
        "sample": {"提交人": "王护士", "姓名": "李医生", "工号": "060101", "科室": "心内科",
                   "审核级别": "科室负责人", "变更内容": "职称：医师 → 主治医师"},
    },
    {
        "code": "staff_change.approved",
        "module": "信息变更审核",
        "label": "信息变更已通过",
        "description": "信息变更审核通过后，通知提交人与被修改人。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "提交人 + 被修改人",
        "related_type": "staff",
        "default_title": "信息变更已通过：{姓名}",
        "default_content": "{审核人} 已通过 {姓名}（{工号}）的信息变更：<br/>{变更内容}",
        "variables": {
            "审核人": "审核人姓名",
            "姓名": "被修改人员姓名",
            "工号": "被修改人员工号",
            "变更内容": "本次变更的字段摘要",
        },
        "sample": {"审核人": "张管理", "姓名": "李医生", "工号": "060101",
                   "变更内容": "职称：医师 → 主治医师"},
    },
    {
        "code": "staff_change.rejected",
        "module": "信息变更审核",
        "label": "信息变更被驳回",
        "description": "信息变更审核驳回后，通知提交人与被修改人（含回滚说明）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "提交人 + 被修改人",
        "related_type": "staff",
        "default_title": "信息变更被驳回：{姓名}",
        "default_content": (
            "{审核人} 驳回了 {姓名}（{工号}）的信息变更：<br/>{变更内容}<br/>"
            "驳回原因：{驳回原因}<br/>{回滚说明}"
        ),
        "variables": {
            "审核人": "审核人姓名",
            "姓名": "被修改人员姓名",
            "工号": "被修改人员工号",
            "变更内容": "本次变更的字段摘要",
            "驳回原因": "审核人填写的驳回原因",
            "回滚说明": "已回滚 / 未自动回滚的原因提示",
        },
        "sample": {"审核人": "张管理", "姓名": "李医生", "工号": "060101", "变更内容": "职称：医师 → 主治医师",
                   "驳回原因": "证明材料不齐", "回滚说明": "相关信息已回滚为修改前的值。"},
    },
    {
        "code": "staff_change.overdue_escalated",
        "module": "信息变更审核",
        "label": "审核超时升级",
        "description": "变更超过设定时长未被审核时，自动升级给超级管理员并通知。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "超级管理员（升级后的审核人）",
        "related_type": "staff_change",
        "default_title": "审核超时升级：{姓名} 的信息变更",
        "default_content": (
            "{提交人} 提交的 {姓名}（{工号} · {科室}）信息变更已超过 {超时小时} 小时未审核，"
            "现升级由超级管理员处理：<br/>{变更内容}"
        ),
        "variables": {
            "提交人": "提交变更的人员姓名",
            "姓名": "被修改人员姓名",
            "工号": "被修改人员工号",
            "科室": "被修改人员所属科室",
            "超时小时": "升级阈值小时数",
            "变更内容": "本次变更的字段摘要",
        },
        "sample": {"提交人": "王护士", "姓名": "李医生", "工号": "060101", "科室": "心内科",
                   "超时小时": "72", "变更内容": "职称：医师 → 主治医师"},
    },
    {
        "code": "staff_change.overdue_reminder",
        "module": "信息变更审核",
        "label": "待审核超时提醒",
        "description": "变更超过设定时长未被审核时，向当前审核人发送一次催办提醒。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "该变更当前的审核人",
        "related_type": "staff_change",
        "default_title": "待审核提醒：{姓名} 的信息变更",
        "default_content": "您有一项待审核的人员信息变更已超过 {超时小时} 小时：<br/>{变更内容}",
        "variables": {
            "姓名": "被修改人员姓名",
            "超时小时": "提醒阈值小时数",
            "变更内容": "本次变更的字段摘要",
        },
        "sample": {"姓名": "李医生", "超时小时": "24", "变更内容": "职称：医师 → 主治医师"},
    },
    # ==================== 系统运维 ====================
    {
        "code": "system.alert",
        "module": "系统运维",
        "label": "系统告警（磁盘 / 数据库）",
        "description": "磁盘空间、数据库体积等系统级告警；同一级别 6 小时内不重复发送。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "拥有「系统配置」或「系统备份」权限的启用账号",
        "related_type": "system_alert",
        "default_title": "[{级别}] {标题}",
        "default_content": "{内容}",
        # 告警正文由系统代码生成（可能含 <br/> 等排版标签），按原文插入不过度转义
        "raw_variables": ["级别", "标题", "内容"],
        "variables": {
            "级别": "告警级别大写，如 WARNING / CRITICAL",
            "标题": "告警标题",
            "内容": "告警正文（含处置建议）",
        },
        "sample": {
            "级别": "WARNING", "标题": "磁盘空间不足",
            "内容": "数据盘剩余空间 8.2%<br/>建议清理历史导出文件。",
        },
    },
    {
        "code": "system.resign_cleanup",
        "module": "系统运维",
        "label": "离职档案清理提醒",
        "description": "离职满保留期的档案已仅保留统计时，提醒超管清理对应登录账号。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "超级管理员",
        "related_type": "system_alert",
        "default_title": "离职档案清理提醒",
        "default_content": (
            "以下员工离职已满 {保留天数} 天（约 6 个月），按保留期策略其档案已仅保留统计："
            "{名单}{更多}。<br/>请前往「用户管理」手动删除其登录账号"
            "（删除账号会一并清理人员档案，离职人数等统计不受影响）。"
        ),
        "variables": {
            "保留天数": "离职档案保留天数",
            "名单": "前若干名人员「姓名（工号）」顿号拼接",
            "更多": "超过展示上限时为「 等共 N 人」，否则为空",
        },
        "sample": {"保留天数": "180", "名单": "李医生（060101）、王护士（060102）", "更多": " 等共 23 人"},
    },
    # ==================== 账号与权限 ====================
    # [新增 2026-09-15] 以下分组的共同背景：这些模块此前**完全没有接入站内信**，
    # 所有改动只写系统日志（record_audit/record_modification），不会主动提醒任何人。
    # 账号、权限、系统配置、通知设置属于"谁能看到什么、谁能做什么"的根本性变更，
    # 一旦被误改而无人知悉，风险远高于普通业务数据，故统一补登记为可配置事件。
    {
        "code": "user.created",
        "module": "账号与权限",
        "label": "新增用户账号",
        "description": "创建用户账号（含批量新建账号）后通知管理方。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "user",
        "default_title": "新增账号：{姓名}",
        "default_content": "{操作人} 新增了用户账号 {姓名}（{工号} · 角色：{角色}）",
        "variables": {
            "操作人": "执行新增的人员姓名",
            "姓名": "新账号姓名",
            "工号": "新账号工号",
            "角色": "新账号角色名称",
            "变更内容": "本次操作的摘要",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "角色": "普通员工", "变更内容": "新增用户账号 李医生(060101) 角色=普通员工"},
    },
    {
        "code": "user.updated",
        "module": "账号与权限",
        "label": "账号信息 / 状态变更",
        "description": "用户账号的姓名、角色、启用状态等信息被修改后通知管理方。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "user",
        "default_title": "账号被修改：{姓名}",
        "default_content": "{操作人} 修改了用户账号 {姓名}({工号})：{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "姓名": "被修改账号的姓名",
            "工号": "被修改账号的工号",
            "变更内容": "本次修改的字段摘要，如「角色: 普通员工 → 科室管理员；状态: 启用 → 停用」",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "变更内容": "角色: 普通员工 → 科室管理员"},
    },
    {
        "code": "user.deleted",
        "module": "账号与权限",
        "label": "删除用户账号",
        "description": "用户账号被删除后通知管理方（账号删除不可逆，属高敏感操作）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "user",
        "default_title": "删除账号：{姓名}",
        "default_content": "{操作人} 删除了用户账号 {姓名}({工号})",
        "variables": {
            "操作人": "执行删除的人员姓名",
            "姓名": "被删除账号的姓名",
            "工号": "被删除账号的工号",
            "变更内容": "本次操作的摘要",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "变更内容": "删除用户账号 李医生(060101)"},
    },
    {
        "code": "user.password_reset",
        "module": "账号与权限",
        "label": "重置账号密码（管理端）",
        "description": "管理员为他人重置登录密码后通知管理方（账号安全敏感操作）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "user",
        "default_title": "账号密码被重置：{姓名}",
        "default_content": "{操作人} 重置了用户账号 {姓名}({工号}) 的登录密码",
        "variables": {
            "操作人": "执行重置的人员姓名",
            "姓名": "被重置密码的账号姓名",
            "工号": "被重置密码的账号工号",
            "变更内容": "本次操作的摘要",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "变更内容": "重置用户账号 李医生(060101) 的登录密码"},
    },
    {
        "code": "user.scope_changed",
        "module": "账号与权限",
        "label": "数据范围 / 科室管辖变更",
        "description": "账号的科室管辖（数据范围）被调整后通知管理方，防止越权访问范围被悄悄放大。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "user",
        "default_title": "数据范围被调整：{姓名}",
        "default_content": "{操作人} 调整了 {姓名}({工号}) 的科室管辖范围：{变更内容}",
        "variables": {
            "操作人": "执行调整的人员姓名",
            "姓名": "被调整的账号姓名",
            "工号": "被调整的账号工号",
            "变更内容": "管辖科室的新增/移除明细",
        },
        "sample": {"操作人": "张管理", "姓名": "李医生", "工号": "060101",
                   "变更内容": "新增管辖科室：心内科、急诊科"},
    },
    {
        "code": "role.changed",
        "module": "账号与权限",
        "label": "角色与权限变更",
        "description": "角色被新建 / 修改权限 / 删除后通知管理方（权限体系变更影响所有使用者）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "role",
        "default_title": "角色与权限变更",
        "default_content": "{操作人} 对角色 {角色} 执行了变更：{变更内容}",
        "variables": {
            "操作人": "执行变更的人员姓名",
            "角色": "被变更的角色名称",
            "变更内容": "本次变更的摘要（新增/删除角色、权限点增减等）",
        },
        "sample": {"操作人": "张管理", "角色": "科室管理员",
                   "变更内容": "权限变更: 新增「删除人员」，移除「导出数据」"},
    },
    {
        "code": "account.security_changed",
        "module": "账号与权限",
        "label": "个人账号安全设置变更",
        "description": "本人修改登录密码 / 换绑邮箱手机号后，给本人发送一条安全提醒（便于发现账号被盗用）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "账号本人",
        # keep_actor：本人操作也要回执给本人（安全提醒的典型场景）
        "keep_actor": True,
        "related_type": "user",
        "default_title": "账号安全设置已变更",
        "default_content": "您的账号安全设置刚刚发生变更：{变更内容}。如非本人操作，请立即联系超级管理员。",
        "variables": {
            "操作人": "操作者姓名（通常为本账号本人）",
            "姓名": "账号姓名",
            "工号": "账号工号",
            "变更内容": "本次变更的摘要，如「登录密码已修改」",
        },
        "sample": {"操作人": "李医生", "姓名": "李医生", "工号": "060101",
                   "变更内容": "登录密码已修改"},
    },
    {
        "code": "registration.submitted",
        "module": "账号与权限",
        "label": "新账号注册申请",
        "description": "有人提交注册申请后提醒超级管理员审核（此前仅停留在待审列表，无主动提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员",
        # 申请人是外部/未登录人员，回落给申请人本人没有意义，故关闭兜底
        "actor_fallback": False,
        "related_type": "user",
        "default_title": "新的注册申请：{姓名}",
        "default_content": "{姓名}（{工号} · {科室}）提交了账号注册申请，请前往「用户管理」审核。",
        "variables": {
            "操作人": "提交人姓名",
            "姓名": "申请人姓名",
            "工号": "申请人工号",
            "科室": "申请人科室",
            "变更内容": "本次操作的摘要",
        },
        "sample": {"操作人": "李医生", "姓名": "李医生", "工号": "060101",
                   "科室": "心内科", "变更内容": "提交注册申请"},
    },
    {
        "code": "registration.reviewed",
        "module": "账号与权限",
        "label": "注册申请审核结果",
        "description": "注册申请被通过或拒绝后通知申请人（此前无任何结果反馈）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_EXPLICIT,
        "default_recipient_hint": "申请人",
        "actor_fallback": False,
        "related_type": "user",
        "default_title": "注册申请{结果}：{姓名}",
        "default_content": "{审核人} {结果}了 {姓名}（{工号}）的账号注册申请{说明}",
        "variables": {
            "审核人": "审核人姓名",
            "姓名": "申请人姓名",
            "工号": "申请人工号",
            "结果": "通过 / 拒绝",
            "说明": "拒绝原因等补充说明（通过时为空）",
            "变更内容": "本次操作的摘要",
        },
        "sample": {"审核人": "张管理", "姓名": "李医生", "工号": "060101",
                   "结果": "通过", "说明": "", "变更内容": "注册申请通过"},
    },
    # ==================== 标识管理 ====================
    {
        "code": "signage.changed",
        "module": "标识管理",
        "label": "标识信息 / 分类变更",
        "description": "标识、标识分类被新增、修改、删除或批量更新科室后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "signage",
        "default_title": "标识变更：{对象}",
        "default_content": "{操作人} 对标识 {对象} 执行了变更：{变更内容}",
        "variables": {
            "操作人": "执行变更的人员姓名",
            "对象": "被变更的标识编号 / 分类名 / 批量范围",
            "变更内容": "本次变更的摘要",
        },
        "sample": {"操作人": "张管理", "对象": "A-01-001", "变更内容": "新增标识（科室: 心内科）"},
    },
    {
        "code": "signage.alert_changed",
        "module": "标识管理",
        "label": "标识报修（发起 / 完成）",
        "description": "标识故障报修被发起或完成后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "signage",
        "default_title": "标识报修：{标识}",
        "default_content": "{操作人} 对标识 {标识} 执行了报修操作：{变更内容}",
        "variables": {
            "操作人": "执行操作的人员姓名",
            "标识": "标识编号",
            "变更内容": "本次操作的摘要，如「发起报修：面板破损」或「报修完成」",
        },
        "sample": {"操作人": "王护士", "标识": "A-01-001", "变更内容": "发起报修：面板破损"},
    },
    {
        "code": "signage.inspection_submitted",
        "module": "标识管理",
        "label": "标识巡检提交",
        "description": "标识巡检结果被提交后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "signage",
        "default_title": "标识巡检提交：{标识}",
        "default_content": "{操作人} 提交了标识 {标识} 的巡检记录：{变更内容}",
        "variables": {
            "操作人": "执行巡检的人员姓名",
            "标识": "标识编号",
            "变更内容": "本次巡检的结果摘要",
        },
        "sample": {"操作人": "王护士", "标识": "A-01-001", "变更内容": "巡检结果: 正常"},
    },
    # ==================== 制度与供应商 ====================
    {
        "code": "regulation.changed",
        "module": "制度与供应商",
        "label": "制度 / 制度分类变更",
        "description": "制度或制度分类被新增、修改、删除后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "regulation",
        "default_title": "制度变更：{对象}",
        "default_content": "{操作人} 对制度 {对象} 执行了变更：{变更内容}",
        "variables": {
            "操作人": "执行变更的人员姓名",
            "对象": "制度标题 / 分类名",
            "变更内容": "本次变更的摘要",
        },
        "sample": {"操作人": "张管理", "对象": "护理交接班制度", "变更内容": "新增制度（分类: 护理管理）"},
    },
    {
        "code": "supplier.changed",
        "module": "制度与供应商",
        "label": "供应商变更",
        "description": "供应商信息被新增、修改、删除后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "supplier",
        "default_title": "供应商变更：{对象}",
        "default_content": "{操作人} 对供应商 {对象} 执行了变更：{变更内容}",
        "variables": {
            "操作人": "执行变更的人员姓名",
            "对象": "供应商名称",
            "变更内容": "本次变更的摘要",
        },
        "sample": {"操作人": "张管理", "对象": "某某医疗设备有限公司", "变更内容": "新增供应商"},
    },
    # ==================== 院区与楼层 ====================
    {
        "code": "campus.changed",
        "module": "院区与楼层",
        "label": "院区 / 楼栋 / 楼层 / 区域变更",
        "description": "院区、楼栋、楼层、区域、楼层平面图被变更后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "campus",
        "default_title": "院区结构变更：{对象}",
        "default_content": "{操作人} 对 {对象} 执行了变更：{变更内容}",
        "variables": {
            "操作人": "执行变更的人员姓名",
            "对象": "院区 / 楼栋 / 楼层 / 区域 名称",
            "变更内容": "本次变更的摘要",
        },
        "sample": {"操作人": "张管理", "对象": "门诊楼 3 层", "变更内容": "新增区域: 心内科诊区"},
    },
    # ==================== 系统配置 ====================
    {
        "code": "system.config_changed",
        "module": "系统配置",
        "label": "系统参数变更",
        "description": "系统配置项（含功能开关）被修改后通知管理方（配置误改会全局生效，此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员",
        "related_type": "system_alert",
        "default_title": "系统配置变更：{对象}",
        "default_content": "{操作人} 修改了系统配置 {对象}：{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "对象": "配置项名称",
            "变更内容": "配置项的新旧值",
        },
        "sample": {"操作人": "张管理", "对象": "是否允许自助注册", "变更内容": "true → false"},
    },
    {
        "code": "branding.changed",
        "module": "系统配置",
        "label": "品牌设置变更",
        "description": "系统名称、Logo、主题色等品牌信息被修改后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员",
        "related_type": "system_alert",
        "default_title": "品牌设置变更",
        "default_content": "{操作人} 修改了品牌设置：{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "对象": "变更范围（如 Logo / 系统名称）",
            "变更内容": "本次修改的摘要",
        },
        "sample": {"操作人": "张管理", "对象": "Logo", "变更内容": "系统名称: 医院信息管理 → 某某医院信息管理"},
    },
    {
        "code": "notification.settings_changed",
        "module": "系统配置",
        "label": "通知设置本身被修改",
        "description": "通知设置（事件开关、收件人规则、文案模板）被修改后通知管理方，防止有人悄悄关掉提醒。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员",
        "related_type": "system_alert",
        "default_title": "通知设置被修改：{对象}",
        "default_content": "{操作人} 修改了通知设置 {对象}：{变更内容}",
        "variables": {
            "操作人": "执行修改的人员姓名",
            "对象": "被修改的事件名称",
            "变更内容": "本次修改的摘要（开关 / 收件人 / 模板）",
        },
        "sample": {"操作人": "张管理", "对象": "人员信息被修改",
                   "变更内容": "收件人规则: 默认 → 仅超级管理员"},
    },
    # ==================== 数据管理 ====================
    # 说明：导入/导出会一次性触碰大量业务数据（或把数据带离系统），
    # 属于最需要留痕与知会的操作，此前仅写系统日志。
    {
        "code": "data.imported",
        "module": "数据管理",
        "label": "数据导入",
        "description": "通过数据导入功能批量写入业务数据后通知管理方（此前只留痕不提醒）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "system_alert",
        "default_title": "数据导入：{对象}",
        "default_content": "{操作人} 执行了数据导入 {对象}：{变更内容}",
        "variables": {
            "操作人": "执行导入的人员姓名",
            "对象": "导入的数据类型（如人员 / 标识 / 供应商）",
            "变更内容": "本次导入的结果摘要（成功 / 失败条数）",
        },
        "sample": {"操作人": "张管理", "对象": "人员",
                   "变更内容": "导入完成：成功 120 条，失败 2 条"},
    },
    {
        "code": "data.exported",
        "module": "数据管理",
        "label": "数据导出",
        "description": "通过数据导出功能批量导出业务数据后通知管理方（数据外带审计）。",
        "default_enabled": True,
        "default_recipients_mode": MODE_MODIFICATION,
        "default_recipient_hint": "超级管理员 + 相关科室管理员（自动排除操作者本人）",
        "related_type": "system_alert",
        "default_title": "数据导出：{对象}",
        "default_content": "{操作人} 导出了 {对象}：{变更内容}",
        "variables": {
            "操作人": "执行导出的人员姓名",
            "对象": "导出的数据类型（如人员 / 标识 / 供应商）",
            "变更内容": "本次导出的范围摘要（条数 / 格式）",
        },
        "sample": {"操作人": "张管理", "对象": "人员",
                   "变更内容": "导出 320 条记录（xlsx）"},
    },
]


# ==================== 查询辅助 ====================

_EVENT_BY_CODE: dict[str, dict] = {e["code"]: e for e in NOTIFICATION_EVENTS}


def get_event(code: str | None) -> dict | None:
    """按事件编码取注册表条目（未知编码返回 None）"""
    return _EVENT_BY_CODE.get((code or "").strip())


def list_events() -> list[dict]:
    """全部已登记事件（按分组顺序返回，供设置页渲染）"""
    order = {name: i for i, name in enumerate(MODULE_ORDER)}
    return sorted(NOTIFICATION_EVENTS, key=lambda e: order.get(e.get("module", ""), 99))


def event_codes() -> list[str]:
    """全部事件编码（用于规则表清理与测试断言）"""
    return [e["code"] for e in NOTIFICATION_EVENTS]


# ==================== 收件人为空时的兜底策略 ====================

def actor_fallback_enabled(event: dict | None) -> bool:
    """收件人解析为空时，是否回落给「操作者本人」作为操作回执

    [新增 2026-09-15] 背景：修改提醒类事件（MODE_MODIFICATION）的默认收件人是
    「启用中的超级管理员 + 相关科室管理员」，并**排除操作者本人**。当系统只有
    一个超管账号、且这次修改正是该超管操作时，排除后收件人集合为空，通知被静默
    丢弃 —— 于是「admin 改完信息，站内信里没有任何记录，看起来像没提醒」。

    修复策略：**只有当收件人解析结果为空时**，才把这条通知回落给操作者本人，
    作为一条可追溯的操作回执（内容与正常通知完全一致）。这样：
        - 有其他人该收到时，行为与之前完全一致（不会多打扰操作者）；
        - 没有任何人能收到时，至少站内信留痕，不再出现"改了却查不到"。
    可在事件登记里用 `"actor_fallback": False` 显式关闭（如注册申请类事件）。
    """
    if not event:
        return False
    if "actor_fallback" in event:
        return bool(event["actor_fallback"])
    return event.get("default_recipients_mode") == MODE_MODIFICATION


def keep_actor_enabled(event: dict | None) -> bool:
    """是否**不排除**操作者本人（默认 False，即按惯例排除）

    用于「本人操作需回执给本人」的场景，例如个人账号安全设置（改密码 / 换绑）
    后给本人发一条安全提醒。
    """
    return bool((event or {}).get("keep_actor"))
