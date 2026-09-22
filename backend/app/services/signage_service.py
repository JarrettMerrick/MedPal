import json
import logging
import re
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from app.models.signage import Signage, FloorPlan, SignagePoint, SignagePhoto, SignageHistory, SignageInspection
from app.models.campus import Campus
from app.models.signage_settings import SignageCategory
from app.utils import beijing_today, utc_now

logger = logging.getLogger("hospital")


def generate_signage_code(db, campus, category, building, floor):
    """[新增 2026-09-07] 自动生成标识编码：院区代号-标识分类-楼栋号-楼层号-三位数

    楼栋号/楼层号缺失（如院区导视类标识）时以两个 0 代替；
    标识分类优先采用分类设置中的编码（如 消防栓 → XF），地下室楼层用 B+两位表示（如 B01）。
    """
    # 院区代号：优先取院区设置中的 code；未设置则取院区名称首字母
    cc = "X"
    if campus:
        campus_obj = db.query(Campus).filter(Campus.name == campus).first()
        if campus_obj and campus_obj.code:
            cc = campus_obj.code
        else:
            cc = str(campus)[:1].upper()

    # 标识分类：优先用分类设置中的编码（如 消防栓 → XF），未匹配则回退分类名称
    cat = "UNKNOWN"
    if category:
        cat_obj = db.query(SignageCategory).filter(SignageCategory.name == category).first()
        if cat_obj and cat_obj.code:
            cat = cat_obj.code
        else:
            cat = str(category).strip() or "UNKNOWN"

    # [修复 2026-09-07] 楼栋号：提取编号数字补零至两位（如 "2号楼"→"02"、"3"→"03"）；
    # 无数字时回退原文；缺失为 00
    bc = "00"
    if building:
        bnum = str(building).split("-")[0].strip()
        m = re.search(r"\d+", bnum)
        if m:
            bc = m.group().zfill(2)
        elif bnum:
            bc = bnum

    # [修复 2026-09-07] 楼层号：统一解析为两位编号——
    #   地下层写法（-1 / B1 / 地下1）→ B01；F3 / 3F / 3 → 03；缺失为 00
    fc = "00"
    if floor:
        fs = str(floor).strip().upper()
        mb = re.match(r"^(?:-|B|地下)\s*(\d+)$", fs)
        if mb:
            fc = f"B{int(mb.group(1)):02d}"
        else:
            mf = re.search(r"\d+", fs)
            if mf:
                fc = f"{int(mf.group()):02d}"

    # 三位数序号：取相同前缀下已有最大序号 + 1
    prefix = f"{cc}-{cat}-{bc}-{fc}"
    # 转义 LIKE 通配符，避免前缀中含有 % 或 _ 时误匹配
    safe_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pat = f"{safe_prefix}-%"
    last = db.query(Signage.code).filter(Signage.code.like(pat, escape="\\")).order_by(Signage.code.desc()).first()
    seq = int(last[0].split("-")[-1]) + 1 if last else 1
    return f"{prefix}-{seq:03d}"


def create_signage(db, data, created_by):
    if not data.get("code"):
        data["code"]=generate_signage_code(
            db,
            data.get("campus", ""),
            data.get("category", ""),
            data.get("building", ""),
            data.get("floor", ""),
        )
    # [新增 2026-09-17] 分类一致性校验：新建时引用的标准设计文件必须与标识分类一致
    if data.get("design_file_id"):
        _validate_design_file_category(db, data.get("category"), data["design_file_id"])
    s=Signage(**data)
    s.created_by=created_by
    s.updated_by=created_by
    db.add(s)
    db.flush()
    # [新增 2026-09-17] 补设计文件使用名（引用标准设计文件时前端需展示使用名）
    _attach_design_file_names(db, [s])
    # [修复 2026-09-04] 创建时记录初始快照
    snapshot = _signage_to_snapshot(s)
    h = SignageHistory(
        signage_id=s.id, field_name=None, old_value=None, new_value=None,
        oa_number=None, changed_by=created_by, changed_at=utc_now(),
        snapshot=json.dumps(snapshot, ensure_ascii=False),
    )
    db.add(h)
    db.flush()
    logger.info(f"[标识管理] 创建标识: {s.code} - {s.name}")
    return s


def _attach_design_file_names(db, signages) -> None:
    """为标识对象补充 design_file_name（取「文件管理」中为该文件设置的使用名）。

    [新增 2026-09-17] 需求：标识引用标准设计文件时，展示名必须用文件库中的
    **使用名**（DesignFile.name），而不是从 design_photo 路径截取出的原始落盘名
    （形如 RC-XX-0-001_design_20260917_101530_ab12cd34.ai，对使用者没有意义）。

    实现要点：
    - 按 design_file_id 一次性 IN 查询，避免逐行 N+1；
    - 以普通 Python 属性挂到 ORM 实例（与上方 department_name 同一套做法），
      供 Pydantic 的 from_attributes 读取，不会写库；
    - 未引用文件库的标识（design_file_id 为空，如早期直接上传的数据）统一置 None，
      前端回退到路径文件名，既有行为不倒退。
    """
    items = [s for s in (signages or []) if s is not None]
    if not items:
        return
    ids = {s.design_file_id for s in items if getattr(s, "design_file_id", None)}
    name_map: dict = {}
    if ids:
        # 函数内导入，避免 services 与 models 之间的循环引用
        from app.models.design_file import DesignFile
        name_map = dict(
            db.query(DesignFile.id, DesignFile.name).filter(DesignFile.id.in_(ids)).all()
        )
    for s in items:
        s.design_file_name = name_map.get(getattr(s, "design_file_id", None))


def _resolve_signage_category_id(db, category_name):
    """标识分类名 → 标识分类 ID；名称不在分类表中时返回 None（无法判定，跳过校验）。"""
    name = (category_name or "").strip()
    if not name:
        return None
    from app.models.signage_settings import SignageCategory
    row = db.query(SignageCategory.id).filter(SignageCategory.name == name).first()
    return row[0] if row else None


def _validate_design_file_category(db, signage_category, design_file_id):
    """校验被引用的设计文件与标识分类一致。

    [新增 2026-09-17] 需求：标识只能引用与其**分类相同**的标准设计文件
    （如分类为「折页」的标识，只能引用文件库中归入「折页」的文件），
    避免跨类别引用造成的数据混乱。

    规则与边界（都在此收敛，避免各调用方口径不一）：
    - 标识分类名不在标识分类表中（历史自由文本 / 分类已被删除）→ 跳过校验，不误伤存量数据；
    - 文件记录不存在 → 跳过（由既有逻辑处理）；
    - 文件未分类、或分类与标识不一致 → 抛 ValueError，由路由转为 400 并给出可操作提示。

    调用时机由上层控制：**仅在「新增引用」或「引用发生变更」时**校验，
    这样存量跨分类数据在编辑其它字段时不会被阻塞。
    """
    target_category_id = _resolve_signage_category_id(db, signage_category)
    if not target_category_id:
        return

    from app.models.design_file import DesignFile
    from app.models.signage_settings import SignageCategory

    record = db.query(DesignFile).filter(DesignFile.id == design_file_id).first()
    if not record:
        return
    if record.category_id == target_category_id:
        return
    if record.category_id is None:
        raise ValueError(
            f"所选设计文件未设置分类，请先在「文件管理」中将其归入「{signage_category}」分类"
        )
    other = db.query(SignageCategory.name).filter(SignageCategory.id == record.category_id).first()
    other_name = other[0] if other else "其它分类"
    raise ValueError(
        f"只能引用与标识分类一致的设计文件：当前标识分类为「{signage_category}」，"
        f"所选文件属于「{other_name}」"
    )


def get_signage(db, signage_id):
    s = db.query(Signage).options(joinedload(Signage.department)).filter(Signage.id==signage_id).first()
    if s:
        s.department_name = s.department.name if s.department else None
        _attach_design_file_names(db, [s])
    return s


def get_signage_list(db, page=1, page_size=20, search=None, category=None, status=None, campus=None, building=None, floor=None, department_id=None, exclude_marked=False, allowed_department_ids=None):
    q=db.query(Signage)
    if search: q=q.filter((Signage.name.like(f"%{search}%"))|(Signage.code.like(f"%{search}%")))
    if category: q=q.filter(Signage.category==category)
    if status: q=q.filter(Signage.status==status)
    if campus: q=q.filter(Signage.campus==campus)
    if building: q=q.filter(Signage.building==building)
    # [新增 2026-09-07] 楼层筛选：与列表页筛选栏联动
    if floor: q=q.filter(Signage.floor==floor)
    if department_id: q=q.filter(Signage.department_id==department_id)
    # [新增 2026-09-08] 按科室作用域过滤：受限角色仅可见其所属科室的标识
    # （含未分配科室的标识，避免作用域用户丢失未归属数据）
    if allowed_department_ids is not None:
        q = q.filter(or_(Signage.department_id.in_(allowed_department_ids), Signage.department_id.is_(None)))
    # [修复 2026-09-05] 标记管理：排除已被标记过的标识（每个标识全局仅可被标记一次）
    if exclude_marked:
        q = q.filter(~Signage.id.in_(db.query(SignagePoint.signage_id)))
    total=q.count()
    items=q.options(joinedload(Signage.department)).order_by(Signage.updated_at.desc()).offset((page-1)*page_size).limit(page_size).all()
    for it in items:
        it.department_name = it.department.name if it.department else None
    # [新增 2026-09-17] 批量补设计文件使用名（一次 IN 查询，避免逐行 N+1）
    _attach_design_file_names(db, items)
    return items, total


def _signage_to_snapshot(s: Signage) -> dict:
    """[修复 2026-09-04] 将标识对象序列化为快照字典"""
    return {
        "code": s.code, "name": s.name, "category": s.category,
        "material": s.material, "size_spec": s.size_spec,
        "install_date": str(s.install_date) if s.install_date else None,
        "warranty_expire": str(s.warranty_expire) if s.warranty_expire else None,
        "campus": s.campus, "building": s.building, "floor": s.floor,
        # [新增 2026-09-12] 所属区域（多选，逗号分隔）；历史版本快照需一并留存
        "area": s.area,
        "location_desc": s.location_desc,
        "display_text_cn": s.display_text_cn, "display_text_en": s.display_text_en,
        "status": s.status, "oa_number": s.oa_number,
        "manufacturer": s.manufacturer,
        "vendor_contact": s.vendor_contact,
        "design_photo": s.design_photo, "installation_photo": s.installation_photo,
    }


def update_signage(db, signage_id, data, updated_by, oa_number=None, record_history=False):
    """[修复 2026-09-04] 更新标识。

    [新增 2026-09-09] record_history：是否记录历史版本（SignageHistory）。
    - 详情页「版本更新」入口传 True：本次修改逐字段写入历史版本并附完整快照；
    - 详情页「编辑」入口（默认 False）：仅更新字段，不生成历史版本记录；
    - 创建标识时的初始快照（create_signage）不受影响。
    """
    s=db.query(Signage).filter(Signage.id==signage_id).first()
    if not s: return None

    # [修复 2026-09-04] 变更前先生成完整快照
    snapshot = _signage_to_snapshot(s)

    # [新增 2026-09-17] 分类一致性校验：**仅在引用发生变化时**校验 ——
    # 存量跨分类引用在编辑其它字段（名称/位置等）时不会被阻塞。
    # 注意必须放在下面的 setattr 循环之前，避免校验失败时留下半更新状态。
    if "design_file_id" in data:
        new_file_id = data.get("design_file_id")
        if new_file_id and new_file_id != s.design_file_id:
            _validate_design_file_category(db, data.get("category") or s.category, new_file_id)

    changed_fields = []
    for key, val in data.items():
        if hasattr(s, key):
            old=getattr(s, key)
            if str(old or "")!=str(val or ""):
                changed_fields.append(key)
                # [新增 2026-09-09] 仅"版本更新"入口（record_history=True）写入历史版本
                if record_history:
                    h=SignageHistory(
                        signage_id=signage_id, field_name=key,
                        old_value=str(old) if old else None,
                        new_value=str(val) if val else None,
                        oa_number=oa_number, changed_by=updated_by,
                        changed_at=utc_now(),
                    )
                    db.add(h)
            setattr(s, key, val)
    s.updated_by=updated_by
    db.flush()

    # [修复 2026-09-04] 将完整快照写入最新一条变更记录（或新增一条汇总记录）
    # [新增 2026-09-09] 仅在记录历史版本时回填快照，普通编辑不产生历史记录
    if changed_fields and record_history:
        # 更新最后一条记录的 snapshot 字段
        last_h = db.query(SignageHistory).filter(
            SignageHistory.signage_id == signage_id
        ).order_by(SignageHistory.id.desc()).first()
        if last_h:
            last_h.snapshot = json.dumps(snapshot, ensure_ascii=False)

    # [新增 2026-09-17] 补设计文件使用名（本次可能刚引用 / 解除了标准设计文件）
    _attach_design_file_names(db, [s])
    return s


def delete_signage(db, signage_id):
    s=db.query(Signage).filter(Signage.id==signage_id).first()
    if not s: return False
    # [修复 2026-09-07] 删除标识时同步清理关联物理文件（双重清理）：
    # 设计文件/现场照片及其 thumb_/orig_ 副本（delete_file 无格式限制，可覆盖 .ai/.pdf），
    # 以及照片记录表中非空的 photo_url 文件；避免残留孤儿文件等待每日定时任务兜底
    from app.services.upload_service import delete_file
    # [新增 2026-09-17] 共享引用保护：设计文件可能被其它标识引用（文件库中的标准设计文件
    # 支持多条标识复用），此时只解除本标识的引用，不清理物理文件，避免影响仍在使用的标识。
    import logging as _logging
    design_shared = False
    try:
        from app.services.design_file_service import is_path_shared
        design_shared = bool(s.design_photo) and is_path_shared(
            db, s.design_photo, exclude_signage_id=signage_id,
        )
    except Exception as exc:
        _logger.warning("删除标识时的共享引用检查失败，按未共享处理: %s", exc)
    if s.design_photo and not design_shared:
        delete_file(s.design_photo)
    if s.installation_photo:
        delete_file(s.installation_photo)
    for (photo_url,) in db.query(SignagePhoto.photo_url).filter(SignagePhoto.signage_id==signage_id).all():
        if photo_url:
            delete_file(photo_url)
    db.query(SignagePoint).filter(SignagePoint.signage_id==signage_id).delete()
    db.query(SignagePhoto).filter(SignagePhoto.signage_id==signage_id).delete()
    db.query(SignageHistory).filter(SignageHistory.signage_id==signage_id).delete()
    db.delete(s)
    db.flush()
    return True


def create_floor_plan(db, data):
    p=FloorPlan(**data)
    db.add(p)
    db.flush()
    return p


def get_floor_plan(db, plan_id):
    return db.query(FloorPlan).filter(FloorPlan.id==plan_id).first()


def get_floor_plan_list(db, campus=None, building=None, category=None):
    # [修复 2026-09-05] 新增 category 平面类别过滤
    q=db.query(FloorPlan).filter(FloorPlan.is_active==True)
    if campus: q=q.filter(FloorPlan.campus==campus)
    if building: q=q.filter(FloorPlan.building==building)
    if category: q=q.filter(FloorPlan.category==category)
    return q.order_by(FloorPlan.campus, FloorPlan.building, FloorPlan.floor).all()


def create_signage_point(db, data):
    p=SignagePoint(**data)
    db.add(p)
    db.flush()
    return p


def get_signage_points(db, floor_plan_id):
    return db.query(SignagePoint).filter(SignagePoint.floor_plan_id==floor_plan_id).all()


def delete_signage_point(db, point_id):
    p=db.query(SignagePoint).filter(SignagePoint.id==point_id).first()
    if not p: return False
    db.delete(p)
    db.flush()
    return True


def get_point_by_signage(db, signage_id, exclude_point_id=None):
    """[新增 2026-09-05] 查询标识是否已被标记；exclude_point_id 用于重新绑定时豁免旧点位"""
    q = db.query(SignagePoint).filter(SignagePoint.signage_id==signage_id)
    if exclude_point_id:
        q = q.filter(SignagePoint.id != exclude_point_id)
    return q.first()


def get_signage_by_code(db, code):
    """[新增 2026-09-05] 按标识编码精确查询（移动巡检手输/扫码用）"""
    s = db.query(Signage).filter(Signage.code == code).first()
    if s:
        _attach_design_file_names(db, [s])
    return s


def create_inspection(db, signage_id, result, inspector, notes=None, photo=None):
    """[新增 2026-09-05] 创建巡检记录，并将巡检结果同步写入标识现有 status 字段"""
    rec = SignageInspection(
        signage_id=signage_id,
        # [修复 2026-09-08] 巡检业务日期改用北京日期：原 UTC 日期在北京时间 00:00-08:00
        # 提交时会记成前一天
        inspection_date=beijing_today(),
        inspector=inspector,
        result=result,
        notes=notes,
        # [新增 2026-09-07] 现场照片路径（客户端压缩后上传，可选）
        photo=photo,
    )
    db.add(rec)
    db.flush()
    s = db.query(Signage).filter(Signage.id == signage_id).first()
    if s:
        s.status = result
        s.updated_by = inspector
    db.flush()
    return rec


def get_inspections(db, page=1, page_size=20, code=None, inspector=None, start=None, end=None,
                    allowed_department_ids=None):
    """[新增 2026-09-05] 巡检历史查询：支持编号/人员模糊与提交时间范围过滤。

    [修复 2026-09-17] 新增 allowed_department_ids 科室范围过滤：原先受限角色
    （department_scope=own/managed）可按编号/日期检索全院巡检历史（含现场照片路径），
    与标识列表的科室过滤口径不一致。None=不限；含未归属科室标识的巡检记录。
    """
    q = db.query(SignageInspection).join(Signage, SignageInspection.signage_id == Signage.id)
    if code:
        q = q.filter(Signage.code.like(f"%{code}%"))
    if inspector:
        q = q.filter(SignageInspection.inspector.like(f"%{inspector}%"))
    if start:
        q = q.filter(SignageInspection.created_at >= start)
    if end:
        q = q.filter(SignageInspection.created_at <= end)
    if allowed_department_ids is not None:
        q = q.filter(or_(Signage.department_id.in_(allowed_department_ids), Signage.department_id.is_(None)))
    total = q.count()
    items = q.order_by(SignageInspection.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def create_signage_photo(db, signage_id, photo_type, photo_url, caption=None, uploaded_by=None):
    p=SignagePhoto(signage_id=signage_id, photo_type=photo_type, photo_url=photo_url, caption=caption, uploaded_by=uploaded_by)
    db.add(p)
    db.flush()
    return p


def get_signage_photos(db, signage_id):
    return db.query(SignagePhoto).filter(SignagePhoto.signage_id==signage_id).all()


def get_signage_history(db, signage_id, page=1, page_size=20):
    q=db.query(SignageHistory).filter(SignageHistory.signage_id==signage_id)
    total=q.count()
    items=q.order_by(SignageHistory.changed_at.desc()).offset((page-1)*page_size).limit(page_size).all()
    return items, total
