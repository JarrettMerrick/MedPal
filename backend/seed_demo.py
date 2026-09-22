# -*- coding: utf-8 -*-
# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""测试数据生成脚本（仅供开发 / 测试环境使用）。

生成内容（随机组合的中文拟真数据）：
    1 个院区 → 多栋楼 → 每栋多个楼层 → 每个楼层多个区域
        （区域按新增的「一个楼层可划分多个区域」规则生成，含同楼层多区域情形）
    科室（临床专科 / 护理病区 / 行政科室）
    标识分类（名称 / 编码 / 颜色 / 标记形状 / 巡检周期）
    供应商（制作厂商）
    人员（users + staff，工号为 6 位数字，与「新增人员」的工号规则一致）
    标识台账（覆盖三种 zone_type；「楼层导视/宣传」的标识带上 0~3 个所属区域，
        用于验证区域「选填 + 多选」）

设计要点：
    - 幂等：每个模块都是「确保至少 N 条」语义。重复执行只会补齐差额，
      不会重复生成第二套院区/人员/标识，可安全地反复运行；
    - 自足：自动保证角色/权限已初始化（等价于应用启动时的初始化），无需先启动后端；
    - 安全：纯新增，不做任何删除或覆盖操作。

数据归属标记：
    本脚本生成的记录统一打上 `updated_by` / `created_by` = "seed_demo"，
    便于识别与日后清理（例如：DELETE FROM staff WHERE updated_by='seed_demo'）。

前置条件：
    项目根目录存在 .env 且已配置 SECRET_KEY（与启动后端的要求一致），
    也可用环境变量 SECRET_KEY / DATABASE_URL 覆盖。

用法（在 backend 目录下执行）：
    python seed_demo.py                                  # 默认规模
    python seed_demo.py --buildings 4 --staff 30 --signages 60
    python seed_demo.py --yes                            # 跳过交互确认
    python seed_demo.py --seed 20260912                  # 固定随机种子，结果可复现
    python seed_demo.py --help
"""

import argparse
import os
import random
import sys
from datetime import date, timedelta

# 允许从任意工作目录执行：把 backend 目录加入 sys.path，保证 `app` 包可导入
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy import or_  # noqa: E402

from app.constants import WORK_TYPE_TO_USER_TYPE  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.campus import Area, Building, Campus, Floor  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.signage import Signage, SignageRepair  # noqa: E402
from app.models.signage_settings import SignageCategory, Supplier  # noqa: E402
from app.models.staff import Staff  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.department_service import create_department  # noqa: E402
from app.services.role_initializer import init_default_roles  # noqa: E402
from app.services.signage_service import create_signage  # noqa: E402
from app.utils import hash_password  # noqa: E402

# 数据归属标记：所有本脚本生成的记录都会带上它，便于识别与清理
MARK = "seed_demo"
# 人员备注标记：与 MARK 组成"双标记"。原因见 seed_staff 中的幂等统计说明——
# 种子人员被管理员在界面上编辑后 updated_by 会变成操作人工号，单靠 MARK 会漏计。
SEED_REMARKS = "测试数据"

# ==================== 数据池 ====================

CAMPUS_POOL = [
    ("康宁院区", "KN"),
    ("滨江院区", "BJ"),
    ("城东院区", "CD"),
    ("新城院区", "XC"),
    ("南湖院区", "NH"),
    ("仁和院区", "RH"),
]

BUILDING_NAME_POOL = [
    "门诊楼", "急诊楼", "住院楼", "医技楼", "行政楼",
    "康复楼", "体检中心", "综合楼", "科教楼", "感染楼",
]

FLOOR_NAME_POOL = [
    "门诊层", "急诊层", "手术层", "住院病区", "检查层",
    "办公层", "康复层", "设备层", "档案层",
]

# 区域名称池：既包含方位类（东/西/南/北区），也包含功能区类
AREA_NAME_POOL = [
    "东区", "西区", "南区", "北区",
    "门诊区", "住院区", "检查区", "治疗区",
    "办公区", "休息区", "候诊区", "设备区",
    "外科区", "内科区", "手术区", "教学区",
]
AREA_TYPES = ["east", "west", "merged"]

# 科室：(名称, 类别, 允许工种)
# allowed_work_types 显式指定，使数据与「工种-科室」校验规则天然一致
DEPARTMENT_POOL = [
    ("内科", "临床专科", "doctor"),
    ("外科", "临床专科", "doctor"),
    ("儿科", "临床专科", "doctor"),
    ("骨科", "临床专科", "doctor"),
    ("心血管内科", "临床专科", "doctor"),
    ("神经内科", "临床专科", "doctor"),
    ("消化内科", "临床专科", "doctor"),
    ("医学影像科", "临床专科", "doctor,technician"),
    ("检验科", "临床专科", "technician"),
    ("一病区", "护理病区", "nurse"),
    ("二病区", "护理病区", "nurse"),
    ("三病区", "护理病区", "nurse"),
    ("手术室", "护理病区", "nurse"),
    ("院办公室", "行政科室", "admin"),
    ("人事科", "行政科室", "admin"),
    ("信息科", "行政科室", "admin"),
    ("设备科", "行政科室", "admin"),
    ("财务科", "行政科室", "admin"),
]

# 标识分类：(名称, 编码, 形状, 颜色, 巡检周期天数/None 表示不参与巡检预警)
CATEGORY_POOL = [
    ("道路指引", "DLZY", "circle", "#2F9E64", 180),
    ("楼层索引", "LCSY", "square", "#1B7FD4", 180),
    ("科室指示牌", "KSZS", "square", "#E8833A", 365),
    ("警示标识", "JZBS", "triangle", "#D9534F", 90),
    ("消防标识", "XFBS", "diamond", "#C0392B", 90),
    ("无障碍标识", "WZZBS", "circle", "#16A085", 365),
    ("宣传栏", "XCL", "square", "#8E44AD", None),
    ("温馨提示牌", "WXTSP", "star", "#F1C40F", None),
    ("禁烟标识", "JYBS", "circle", "#7F8C8D", 180),
    ("出口指示", "CKZS", "diamond", "#27AE60", 180),
]

# 供应商：(名称, 联系人, 电话, 地址)
SUPPLIER_POOL = [
    ("南通华宇标识制作有限公司", "张建国", "13800001111", "南通市崇川区人民路 88 号"),
    ("江苏金石广告工程有限公司", "李海峰", "13800002222", "南京市江宁区科学园 12 号"),
    ("上海远景导视系统有限公司", "王雪梅", "13800003333", "上海市嘉定区安亭镇园大路 5 号"),
    ("苏州雅标工艺制品有限公司", "陈立新", "13800004444", "苏州市吴中区木渎镇金枫路 66 号"),
]

SURNAMES = [
    "赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈",
    "褚", "卫", "蒋", "沈", "韩", "杨", "朱", "秦", "许", "何",
]
GIVEN_NAMES = [
    "伟", "强", "磊", "军", "洋", "勇", "杰", "涛", "明", "超",
    "鹏", "斌", "辉", "健", "俊", "浩", "芳", "娜", "敏", "静",
    "丽", "娟", "艳", "霞", "燕", "婷", "雪", "颖", "琳", "倩",
]

TITLES = {
    "doctor": ["主任医师", "副主任医师", "主治医师", "住院医师"],
    "nurse": ["主任护师", "副主任护师", "主管护师", "护师", "护士"],
    "technician": ["主任技师", "主管技师", "技师", "技士"],
    "admin": ["科长", "副科长", "科员"],
}
EDUCATIONS = ["博士研究生", "硕士研究生", "本科", "本科", "大专"]
EXPERTISE_TPL = [
    "{dept}常见病与多发病的诊治",
    "{dept}疑难病例诊治与随访管理",
    "{dept}规范化诊疗与健康宣教",
    "{dept}临床护理与并发症预防",
    "{dept}影像诊断与质量控制",
    "{dept}设备维护与技术支持",
]
POSITIONS = ["", "科室副主任", "护士长", "组长", "负责人"]
MATERIALS = ["铝型材", "亚克力", "不锈钢", "镀锌板烤漆", "PVC", "木质复合"]
SIZES = ["400x200mm", "600x300mm", "800x400mm", "900x600mm", "1200x600mm", "1500x800mm"]
DISPLAY_EN = {
    "道路指引": "Wayfinding",
    "楼层索引": "Floor Directory",
    "科室指示牌": "Department Sign",
    "警示标识": "Warning Sign",
    "消防标识": "Fire Safety Sign",
    "无障碍标识": "Accessibility Sign",
    "宣传栏": "Bulletin Board",
    "温馨提示牌": "Notice Sign",
    "禁烟标识": "No Smoking Sign",
    "出口指示": "Exit Sign",
}
LOCATIONS = [
    "门诊大厅入口", "门诊前立柱旁", "电梯厅对面", "大厅服务台右侧",
    "楼梯口墙面上方", "走廊尽头转角处", "候诊区座椅上方", "护士站侧墙",
    "住院部电梯口", "各楼层单元门口", "地下车库入口", "连廊柱体表面",
]
STATUS_POOL = ["normal"] * 12 + ["damaged"] * 2 + ["repair_in_progress"] + ["severely_damaged"]
ZONE_TYPES = ["院区导视/宣传", "楼栋导视/宣传", "楼层导视/宣传"]
# 「工号-科室」校验中 doctor→临床专科 / nurse→护理病区 的兜底映射，
# 这里仅用于在科室未配置 allowed_work_types 时挑一个合理工种
FALLBACK_WORK_TYPE = {"临床专科": "doctor", "护理病区": "nurse", "行政科室": "admin"}


# ==================== 工具函数 ====================


def random_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN_NAMES)


def floor_label(floor: Floor) -> str:
    """与前端 utils/floor.ts 的 floorLabel 口径保持一致（如 F3-门诊层）。

    [调整 2026-09-17] 楼层号已改为字母编号（F3 / B1），无需再手工拼接 F 后缀。
    """
    base = floor.floor_number or ""
    return f"{base}-{floor.floor_name}" if floor.floor_name else base


def building_label(building: Building) -> str:
    """与前端 SignageForm 的楼栋展示口径保持一致（如 1-门诊楼）。"""
    return f"{building.building_number}-{building.name}"


def pick_new_from_pool(rng: random.Random, pool: list, existing_keys: set, need: int, key_index: int = 0):
    """从池中挑出 need 个尚未创建的条目（保证重复执行不再新增）。"""
    remaining = [item for item in pool if item[key_index] not in existing_keys]
    rng.shuffle(remaining)
    return remaining[:need]


# ==================== 各模块生成 ====================


def seed_campus(db, rng, buildings_count, floors_count, areas_min, areas_max):
    """生成 1 个院区 + 多栋楼 + 多层楼 + 每层多区域（幂等）。"""
    pool_names = [name for name, _ in CAMPUS_POOL]

    # 幂等关键：已存在任一「测试院区池」中的院区就复用，不再新建第二个院区
    campus = db.query(Campus).filter(Campus.name.in_(pool_names)).order_by(Campus.id).first()
    if campus:
        print(f"  · 复用已有院区「{campus.name}」（代号 {campus.code}）")
        name, code = campus.name, campus.code
    else:
        name, code = rng.choice(CAMPUS_POOL)
        campus = Campus(
            name=name,
            code=code,
            description=f"{name}测试数据（由 seed_demo.py 生成）",
            address=f"测试市测试区示例路 {rng.randint(1, 199)} 号",
            is_active=True,
            created_by=MARK,
            updated_by=MARK,
        )
        db.add(campus)
        db.flush()
        print(f"  · 新建院区「{name}」（代号 {code}）")

    # 楼栋：编号用 1、2、3…，名称从池中不重复抽取
    building_names = rng.sample(BUILDING_NAME_POOL, min(buildings_count, len(BUILDING_NAME_POOL)))
    buildings = []
    for idx, bname in enumerate(building_names, start=1):
        number = str(idx)
        b = (
            db.query(Building)
            .filter(Building.campus_id == campus.id, Building.building_number == number)
            .first()
        )
        if b:
            buildings.append(b)
            continue
        b = Building(
            campus_id=campus.id,
            name=bname,
            building_number=number,
            description=f"{bname}测试楼栋",
            is_active=True,
            created_by=MARK,
            updated_by=MARK,
        )
        db.add(b)
        db.flush()
        buildings.append(b)
    print(f"  · 楼栋 {len(buildings)} 栋：{', '.join(building_label(b) for b in buildings)}")

    # 楼层 + 区域：只补齐差额，重复执行不会重复新增
    total_floors = 0
    total_areas = 0
    floor_names = rng.sample(FLOOR_NAME_POOL, min(floors_count, len(FLOOR_NAME_POOL)))
    for b in buildings:
        for fno in range(1, floors_count + 1):
            # [调整 2026-09-17] 楼层号改为字母编号：地上 fno 层记为 F{fno}
            floor_number = f"F{fno}"
            fl = (
                db.query(Floor)
                .filter(Floor.building_id == b.id, Floor.floor_number == floor_number)
                .first()
            )
            if not fl:
                fl = Floor(
                    building_id=b.id,
                    floor_number=floor_number,
                    floor_name=floor_names[(fno - 1) % len(floor_names)],
                    description=f"{b.name} F{fno} 测试楼层",
                    is_active=True,
                    created_by=MARK,
                    updated_by=MARK,
                )
                db.add(fl)
                db.flush()
            total_floors += 1

            rows = db.query(Area).filter(Area.floor_id == fl.id).all()
            existing = len(rows)
            # 严格幂等：该楼层已有区域（无论本脚本生成还是人工维护）就不再新增，
            # 避免重复执行时区域数量在 areas_min~areas_max 之间不断漂移
            if existing > 0:
                total_areas += existing
                continue
            want = rng.randint(areas_min, areas_max)

            # 同一楼层内区域名不重复，避免标识多选时取值冲突；名称不足时追加序号
            used_names = {a.name for a in rows}
            candidates = [n for n in AREA_NAME_POOL if n not in used_names]
            rng.shuffle(candidates)
            for i in range(want - existing):
                if i < len(candidates):
                    aname = candidates[i]
                else:
                    aname = f"{rng.choice(AREA_NAME_POOL)}{existing + i + 1}"
                db.add(
                    Area(
                        floor_id=fl.id,
                        name=aname,
                        # 区域类型仅作分类标签，允许同楼层出现多个同类型区域
                        area_type=rng.choice(AREA_TYPES),
                        description=f"{fl.floor_name or fl.floor_number}·{aname}",
                        is_active=True,
                        created_by=MARK,
                        updated_by=MARK,
                    )
                )
                total_areas += 1
            db.flush()
    print(f"  · 楼层 {total_floors} 个，区域 {total_areas} 个（每层 {areas_min}~{areas_max} 个）")
    return campus, buildings


def seed_departments(db, rng, count):
    """确保至少 count 个池内科室存在（幂等）。"""
    pool_names = [name for name, _, _ in DEPARTMENT_POOL]
    existing = {
        d.name for d in db.query(Department).filter(Department.name.in_(pool_names)).all()
    }
    need = max(0, count - len(existing))
    for dname, category, allowed in pick_new_from_pool(rng, DEPARTMENT_POOL, existing, need):
        create_department(
            db,
            name=dname,
            description=f"{dname}测试科室介绍（由 seed_demo.py 生成）",
            category=category,
            allowed_work_types=allowed,
        )
        existing.add(dname)
    db.flush()
    rows = db.query(Department).filter(Department.name.in_(pool_names)).all()
    print(f"  · 科室 {len(rows)} 个（本次新增 {need}）：{', '.join(d.name for d in rows)}")
    return rows


def seed_categories(db, rng, count):
    """确保至少 count 个池内标识分类存在（幂等）。"""
    pool_names = [name for name, _, _, _, _ in CATEGORY_POOL]
    existing = {
        c.name for c in db.query(SignageCategory).filter(SignageCategory.name.in_(pool_names)).all()
    }
    need = max(0, count - len(existing))
    for cname, ccode, shape, color, cycle in pick_new_from_pool(rng, CATEGORY_POOL, existing, need):
        db.add(
            SignageCategory(
                name=cname,
                code=ccode,
                description=f"{cname}（测试分类）",
                color=color,
                shape=shape,
                inspection_cycle_days=cycle,
                is_active=True,
            )
        )
        existing.add(cname)
    db.flush()
    rows = db.query(SignageCategory).filter(SignageCategory.name.in_(pool_names)).all()
    print(f"  · 标识分类 {len(rows)} 个（本次新增 {need}）：{', '.join(c.name for c in rows)}")
    return rows


def seed_suppliers(db, rng, count):
    """确保至少 count 个池内供应商存在（幂等）。"""
    pool_names = [name for name, _, _, _ in SUPPLIER_POOL]
    existing = {s.name for s in db.query(Supplier).filter(Supplier.name.in_(pool_names)).all()}
    need = max(0, count - len(existing))
    for sname, contact, phone, addr in pick_new_from_pool(rng, SUPPLIER_POOL, existing, need):
        db.add(
            Supplier(
                name=sname,
                type="manufacturer",
                contact_person=contact,
                phone=phone,
                address=addr,
                email=f"test{rng.randint(100, 999)}@example.com",
                is_active=True,
            )
        )
        existing.add(sname)
    db.flush()
    rows = db.query(Supplier).filter(Supplier.name.in_(pool_names)).all()
    print(f"  · 供应商 {len(rows)} 家（本次新增 {need}）：{', '.join(s.name for s in rows)}")
    return rows


def seed_staff(db, rng, departments, count, password):
    """确保至少 count 名测试人员存在（幂等，按 updated_by=MARK 统计）。

    注意：staff.employee_id 外键指向 users.employee_id（ON DELETE CASCADE），
    因此必须先建登录账号、再建人员档案。
    """
    employee_role = db.query(Role).filter(Role.name == "employee").first()
    if employee_role is None:
        raise RuntimeError("未找到「普通员工」角色，请先启动一次后端以初始化角色与权限")

    # 幂等统计：updated_by=MARK（未被编辑过）与 remarks=SEED_REMARKS（被编辑过但仍是种子人员）
    # 取并集。仅用 updated_by 会在种子人员被管理员界面编辑后漏计，导致重复补建。
    already = db.query(Staff).filter(
        or_(Staff.updated_by == MARK, Staff.remarks == SEED_REMARKS)
    ).count()
    need = max(0, count - already)
    if need == 0:
        print(f"  · 人员已存在 {already} 名（目标 {count}），跳过")
        return already

    def next_employee_id(start: int) -> int:
        """从 start 起找到第一个未被占用的工号（测试工号统一使用 9xxxxx 段）。"""
        candidate = start
        while db.query(User).filter(User.employee_id == str(candidate)).first():
            candidate += 1
        return candidate

    cursor = next_employee_id(900001)
    for _ in range(need):
        cursor = next_employee_id(cursor)
        emp = str(cursor)
        cursor += 1

        dept = rng.choice(departments)
        # 工种必须落在该科室允许的工种内，保持与「工种-科室」校验规则一致
        if dept.allowed_work_types:
            allowed = [w.strip() for w in dept.allowed_work_types.split(",") if w.strip()]
        else:
            allowed = [FALLBACK_WORK_TYPE.get(dept.category, "doctor")]
        work_type = rng.choice(allowed) if allowed else "doctor"

        name = random_name(rng)
        title = rng.choice(TITLES.get(work_type, ["科员"]))
        expertise = rng.choice(EXPERTISE_TPL).format(dept=dept.name)

        db.add(
            User(
                employee_id=emp,
                name=name,
                password_hash=hash_password(password),
                role="employee",
                role_id=employee_role.id,
                department=dept.name,
                user_type=WORK_TYPE_TO_USER_TYPE.get(work_type, "admin_user"),
                is_active=True,
                # 测试账号免去首登强制改密，方便直接登录
                must_change_password=False,
            )
        )
        db.flush()

        db.add(
            Staff(
                employee_id=emp,
                name=name,
                work_type=work_type,
                education=rng.choice(EDUCATIONS),
                title=title,
                department=dept.name,
                position=rng.choice(POSITIONS) or None,
                expertise_short=expertise,
                expertise_standard=(
                    f"{expertise}。从事{dept.name}工作多年，具备扎实的理论基础与丰富的临床经验。"
                ),
                social_appointments=rng.choice(["", "市医学会会员", "省级专业委员会委员"]) or None,
                honors=rng.choice(["", "年度优秀员工", "医德医风先进个人"]) or None,
                remarks=SEED_REMARKS,
                status="active",
                updated_by=MARK,
            )
        )
        db.flush()

    total = already + need
    print(f"  · 人员 {total} 名（本次新增 {need}，工号自 900001 起，登录口令均为 {password}）")
    return total


def seed_signages(db, rng, campus, buildings, categories, suppliers, departments, count):
    """确保至少 count 条测试标识存在（幂等，按 created_by=MARK 统计）。

    覆盖三种 zone_type；「楼层导视/宣传」按 0 个 / 1 个 / 多个区域生成，
    用于验证区域「选填 + 多选」。
    """
    if not categories:
        print("  · 无标识分类，跳过标识生成")
        return 0

    already = db.query(Signage).filter(Signage.created_by == MARK).count()
    need = max(0, count - already)
    if need == 0:
        print(f"  · 标识已存在 {already} 条（目标 {count}），跳过")
        return already

    floors_by_building = {
        b.id: db.query(Floor).filter(Floor.building_id == b.id).all() for b in buildings
    }
    areas_by_floor = {}
    created = 0
    for _ in range(need):
        b = rng.choice(buildings)
        floors = floors_by_building.get(b.id) or []
        if not floors:
            continue
        fl = rng.choice(floors)

        if fl.id not in areas_by_floor:
            areas_by_floor[fl.id] = (
                db.query(Area).filter(Area.floor_id == fl.id, Area.is_active == True).all()
            )
        areas_of_floor = areas_by_floor[fl.id]

        zone_type = rng.choice(ZONE_TYPES)
        cat = rng.choice(categories)
        dept = rng.choice(departments) if departments and rng.random() < 0.6 else None
        location = rng.choice(LOCATIONS)

        # 区域：仅「楼层导视/宣传」可填，且为选填、支持多选
        picked_areas = []
        if zone_type == "楼层导视/宣传" and areas_of_floor:
            roll = rng.random()
            if roll < 0.25:
                picked_areas = []                                    # 不选区域
            elif roll < 0.55:
                picked_areas = [rng.choice(areas_of_floor)]           # 选 1 个
            else:
                picked_areas = rng.sample(                            # 选多个
                    areas_of_floor, min(len(areas_of_floor), rng.randint(2, 3))
                )
        area_value = ",".join(a.name for a in picked_areas) if picked_areas else None

        validity_type = "temporary" if rng.random() < 0.15 else "long_term"
        install = date.today() - timedelta(days=rng.randint(30, 900))
        payload = {
            # 留空 → 由 create_signage 按「院区代号-分类编码-楼栋号-楼层号-序号」自动编码
            "code": None,
            "name": f"{location}{cat.name}",
            "category": cat.name,
            "category_type": "平面宣传" if rng.random() < 0.15 else "标识标牌",
            "material": rng.choice(MATERIALS),
            "size_spec": rng.choice(SIZES),
            "install_date": install,
            "warranty_expire": install + timedelta(days=365),
            "validity_type": validity_type,
            "validity_until": (
                install + timedelta(days=rng.randint(180, 900))
                if validity_type == "temporary" else None
            ),
            "campus": campus.name,
            "building": building_label(b),
            "floor": floor_label(fl),
            "area": area_value,
            "zone_type": zone_type,
            "location_desc": location,
            "display_text_cn": f"{cat.name}·{b.name}{floor_label(fl)}",
            "display_text_en": DISPLAY_EN.get(cat.name),
            "department_id": dept.id if dept else None,
            "status": rng.choice(STATUS_POOL),
            "oa_number": f"OA{date.today().strftime('%Y%m')}{rng.randint(1, 9999):04d}",
            "manufacturer": rng.choice(suppliers).name if suppliers else None,
            "vendor_contact": rng.choice(["13800001111", "13800002222", "13800003333"]),
        }
        # 走服务层创建：自动生成唯一编码并写入初始快照（与页面新增行为一致）
        create_signage(db, payload, MARK)
        created += 1
        db.flush()

    print(f"  · 标识 {already + created} 条（本次新增 {created}；含不带区域 / 带 1 个 / 带多个区域）")
    return already + created


def ensure_open_repairs(db, rng):
    """保证「维修处理中」的测试标识都有对应的未完成维修记录（幂等）。

    背景：「维修处理中」在系统里有两处来源，必须保持一致——
      1) signages.status = 'repair_in_progress'：详情页 / 标识列表页的状态徽章；
      2) signage_repairs 中 completed_at 为空的记录：预警页「维修处理中」列表，
         并据此提供「完成维修」入口。
    应用自身的 start_repair() 会同时写这两者；若种子数据只写状态而不建记录，
    就会出现「详情页显示维修处理中、预警页却查不到该条、也无法完成维修」的不一致，
    标识会卡在该状态无法恢复。
    """
    rows = (
        db.query(Signage)
        .filter(Signage.created_by == MARK, Signage.status == "repair_in_progress")
        .all()
    )
    fixed = 0
    for s in rows:
        opened = (
            db.query(SignageRepair)
            .filter(SignageRepair.signage_id == s.id, SignageRepair.completed_at.is_(None))
            .first()
        )
        if opened:
            continue
        party = rng.choice(["engineering", "vendor"])
        sup = (
            db.query(Supplier).filter(Supplier.is_active.is_(True)).first()
            if party == "vendor" else None
        )
        db.add(
            SignageRepair(
                signage_id=s.id,
                repair_party=party,
                supplier_id=sup.id if sup else None,
                supplier_name=sup.name if sup else None,
                repair_photo_before=None,
                started_by=MARK,
            )
        )
        fixed += 1
    db.flush()
    return fixed


# ==================== 入口 ====================


def main():
    parser = argparse.ArgumentParser(
        description="生成 MedPal 测试数据（院区/楼栋/楼层/区域/科室/标识分类/供应商/人员/标识）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--buildings", type=int, default=3, help="楼栋数量")
    parser.add_argument("--floors", type=int, default=5, help="每栋楼的楼层数量")
    parser.add_argument("--areas-min", type=int, default=2, help="每层最少区域数")
    parser.add_argument("--areas-max", type=int, default=4, help="每层最多区域数")
    parser.add_argument("--departments", type=int, default=10, help="科室数量（上限为内置池大小）")
    parser.add_argument("--categories", type=int, default=8, help="标识分类数量（上限为内置池大小）")
    parser.add_argument("--suppliers", type=int, default=3, help="供应商数量（上限为内置池大小）")
    parser.add_argument("--staff", type=int, default=20, help="人员数量")
    parser.add_argument("--signages", type=int, default=40, help="标识数量")
    parser.add_argument("--password", default="MedPal@Test2026", help="测试账号登录口令（所有账号相同）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（固定后结果可复现）")
    parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = parser.parse_args()

    if args.buildings < 1 or args.floors < 1:
        parser.error("--buildings 与 --floors 必须 >= 1")
    if args.areas_min < 1 or args.areas_max < args.areas_min:
        parser.error("--areas-min 需 >= 1，且 --areas-max 需 >= --areas-min")
    if len(args.password) < 6:
        parser.error("--password 长度至少 6 位（与注册/改密的长度要求一致）")

    rng = random.Random(args.seed)

    print("=" * 72)
    print("MedPal 测试数据生成")
    print("=" * 72)
    print(f"数据库: {engine.url}")
    print(f"规模  : 楼栋 {args.buildings} / 每栋楼层 {args.floors} / 每层区域 "
          f"{args.areas_min}~{args.areas_max} / 科室 {args.departments} / 分类 {args.categories} / "
          f"供应商 {args.suppliers} / 人员 {args.staff} / 标识 {args.signages}")
    print("说明  : 纯新增，不删除不覆盖；重复执行只补齐差额（幂等），可安全反复运行。")
    print("-" * 72)

    if not args.yes and sys.stdin.isatty():
        answer = input("确认写入以上数据库？(y/N) ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消。")
            return 1

    db = SessionLocal()
    try:
        # 1) 建表 + 角色/权限初始化（与后端启动时完全一致，幂等）
        Base.metadata.create_all(bind=engine)
        from app import models as _all_models  # noqa: F401  确保所有模型已注册到 Base.metadata
        init_default_roles(db)
        db.commit()

        print("[1/6] 院区 / 楼栋 / 楼层 / 区域")
        campus, buildings = seed_campus(
            db, rng, args.buildings, args.floors, args.areas_min, args.areas_max
        )
        db.commit()

        print("[2/6] 科室")
        departments = seed_departments(db, rng, args.departments)
        db.commit()

        print("[3/6] 标识分类")
        categories = seed_categories(db, rng, args.categories)
        db.commit()

        print("[4/6] 供应商")
        suppliers = seed_suppliers(db, rng, args.suppliers)
        db.commit()

        print("[5/6] 人员（含登录账号）")
        seed_staff(db, rng, departments, args.staff, args.password)
        db.commit()

        print("[6/6] 标识台账与维修记录一致性")
        seed_signages(db, rng, campus, buildings, categories, suppliers, departments, args.signages)
        # 一致性保障：status=repair_in_progress 的标识必须存在未完成维修记录，
        # 否则预警页看不到「维修处理中」，也无法执行「完成维修」（详见函数注释）
        fixed = ensure_open_repairs(db, rng)
        if fixed:
            print(f"  · 补建未完成维修记录 {fixed} 条（使「维修处理中」状态与预警数据一致）")
        db.commit()

        print("-" * 72)
        print("完成。测试提示：")
        print("  · 管理员账号 admin 由后端首次启动自动创建（初始口令 MedPal@admin，首登需改密）")
        print(f"  · 本次测试账号工号自 900001 起，口令统一为 {args.password}（已设为首登免改密）")
        print("  · 「院区管理」中该院区每个楼层均有多个区域，可验证「一楼层多区域」")
        print("  · 「标识管理」中筛选 zone_type=楼层导视/宣传，可验证区域「选填 + 多选」")
        print(f"  · 数据标记: 本脚本生成的记录 updated_by/created_by = '{MARK}'，便于日后清理")
        print("  · 本脚本不提供删除功能；如需清空测试数据，请从界面删除或恢复备份")
        return 0
    except Exception as exc:  # noqa: BLE001  脚本需给出完整失败原因
        db.rollback()
        print(f"\n[失败] {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
