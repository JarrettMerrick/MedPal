# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

# [修复 2026-09-01] 添加 Request 导入，用于获取客户端 IP 地址记录到系统日志
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
import re

from app.database import get_db
from app.dependencies import get_current_user, require_permission, PERM_REGULATION_VIEW, PERM_REGULATION_CREATE, PERM_REGULATION_EDIT, PERM_REGULATION_DELETE
from app.models.user import User
from app.models.regulation import Regulation, RegulationCategory, RegulationHistory
from app.schemas.regulation import (
    CategoryCreate, CategoryUpdate, CategoryOut,
    RegulationCreate, RegulationUpdate, RegulationOut, RegulationDetailOut, RegulationListOut,
    RegulationHistoryOut, RegulationHistoryDetailOut,
)
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：制度 / 制度分类变更后通知管理方
from app.services.modification_notify import notify_super_admins
from app.utils import utc_now, get_client_ip

router = APIRouter(prefix="/api/regulations", tags=["制度管理"])


def _notify_regulation_change(db: Session, current_user: User, obj_label: str, summary: str) -> None:
    """[新增 2026-09-15] 制度变更站内信（制度 / 分类共用出口，失败静默）

    制度与分类的增删改此前只留痕不提醒，管理方无从知晓制度库变化；
    在每个写端点留痕后统一补发站内信（事件：regulation.changed）。
    """
    try:
        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"制度变更：{obj_label}",
            content=f"{modifier_name} {summary}",
            related_type="regulation",
            exclude_user_id=current_user.employee_id,
            event_code="regulation.changed",
            context={"操作人": modifier_name, "对象": obj_label, "变更内容": summary},
        )
        db.commit()
    except Exception:
        db.rollback()


# ==================== 类别管理 ====================

@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    current_user: User = Depends(require_permission(PERM_REGULATION_VIEW)),
    db: Session = Depends(get_db),
):
    """获取所有制度类别（需查看制度权限）"""
    return db.query(RegulationCategory).order_by(RegulationCategory.sort_order, RegulationCategory.id).all()


@router.post("/categories", response_model=CategoryOut)
def create_category(
    data: CategoryCreate,
    request: Request,
    current_user: User = Depends(require_permission(PERM_REGULATION_CREATE)),
    db: Session = Depends(get_db),
):
    """新增制度类别（需新增制度权限）

    [新增] 类别代码 code 必填且为3位大写英文字母，名称与代码均唯一。
    """
    if db.query(RegulationCategory).filter(RegulationCategory.name == data.name).first():
        raise HTTPException(400, "该类别名称已存在")
    if db.query(RegulationCategory).filter(RegulationCategory.code == data.code).first():
        raise HTTPException(400, f"类别代码 {data.code} 已存在")
    cat = RegulationCategory(name=data.name, code=data.code, sort_order=data.sort_order)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    # [改进/A2] 类别新增留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "regulation_category_create", current_user.employee_id,
                     detail=f"name={cat.name} code={cat.code}", target=str(cat.id), ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    # [新增 2026-09-15] 补发站内信（事件：regulation.changed）
    _notify_regulation_change(
        db, current_user, f"分类「{cat.name}」",
        f"新增了制度分类「{cat.name}」（代码 {cat.code}）",
    )
    return cat


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    request: Request,
    current_user: User = Depends(require_permission(PERM_REGULATION_DELETE)),
    db: Session = Depends(get_db),
):
    """删除制度类别（需删除制度权限）"""
    cat = db.query(RegulationCategory).filter(RegulationCategory.id == category_id).first()
    if not cat:
        raise HTTPException(404, "类别不存在")
    count = db.query(Regulation).filter(Regulation.category_id == category_id).count()
    if count > 0:
        raise HTTPException(400, f"该类别下有 {count} 条制度，无法删除")
    cat_name = cat.name
    db.delete(cat)
    db.commit()
    # [改进/A2] 类别删除留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "regulation_category_delete", current_user.employee_id,
                     detail=f"name={cat_name}", target=str(category_id), ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    # [新增 2026-09-15] 补发站内信（事件：regulation.changed）
    _notify_regulation_change(db, current_user, f"分类「{cat_name}」", f"删除了制度分类「{cat_name}」")
    return {"message": "删除成功"}


@router.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    data: CategoryUpdate,
    request: Request,
    current_user: User = Depends(require_permission(PERM_REGULATION_EDIT)),
    db: Session = Depends(get_db),
):
    """[新增] 编辑制度类别名称/代码（需编辑制度权限）"""
    cat = db.query(RegulationCategory).filter(RegulationCategory.id == category_id).first()
    if not cat:
        raise HTTPException(404, "类别不存在")
    # 记录修改前的值
    old_name, old_code = cat.name, cat.code
    changes = []
    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(400, "类别名称不能为空")
        dup = db.query(RegulationCategory).filter(
            RegulationCategory.name == data.name,
            RegulationCategory.id != category_id,
        ).first()
        if dup:
            raise HTTPException(400, "该类别名称已存在")
        if data.name != old_name:
            changes.append(f"名称: {old_name} → {data.name}")
        cat.name = data.name
    if data.code is not None:
        dup = db.query(RegulationCategory).filter(
            RegulationCategory.code == data.code,
            RegulationCategory.id != category_id,
        ).first()
        if dup:
            raise HTTPException(400, f"类别代码 {data.code} 已存在")
        if data.code != old_code:
            changes.append(f"代码: {old_code} → {data.code}")
        cat.code = data.code
    db.commit()
    db.refresh(cat)
    # [修复 2026-09-01] 类别编辑留痕（原先缺失）
    if changes:
        try:
            client_ip = get_client_ip(request)
            record_audit(db, "regulation_category_update", current_user.employee_id,
                         detail="；".join(changes), target=str(category_id), ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()
        # [新增 2026-09-15] 补发站内信（事件：regulation.changed；仅在字段确有变化时发送）
        _notify_regulation_change(
            db, current_user, f"分类「{cat.name}」",
            "修改了制度分类「{}」：{}".format(cat.name, "；".join(changes)),
        )
    return cat


# ==================== 版本号生成 ====================

def _gen_version(reg: Regulation, category_code: str) -> str:
    """[新增] 自动生成下一个版本号：V{01-99}_{类别代码}_{YYMMDD}

    数字从 01 开始，每次+1，99 后变 00。类别代码从 category.code 取，无类别用 "XXX"。
    """
    num = 1
    if reg.id and reg.history and len(reg.history) > 0:
        m = re.match(r'^V(\d{2})_', reg.history[0].version or '')
        if m:
            num = int(m.group(1)) + 1
            if num > 99:
                num = 0
    date_part = utc_now().strftime("%y%m%d")
    return f"V{num:02d}_{category_code}_{date_part}"


def _record_history(
    reg: Regulation, version: str, content: str, editor: str, change_summary: str = "",
) -> RegulationHistory:
    """[新增] 创建一条版本历史记录（含版本号+内容快照）"""
    return RegulationHistory(
        regulation_id=reg.id,
        version=version,
        content=content,
        edited_by=editor,
        change_summary=change_summary,
    )


# ==================== 制度管理 ====================

@router.get("", response_model=RegulationListOut)
def list_regulations(
    keyword: str = Query("", description="搜索关键词"),
    category_id: int = Query(0, description="类别筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission(PERM_REGULATION_VIEW)),
    db: Session = Depends(get_db),
):
    """获取制度列表（需查看制度权限）"""
    q = db.query(Regulation)
    if keyword:
        q = q.filter(Regulation.name.contains(keyword))
    if category_id:
        q = q.filter(Regulation.category_id == category_id)
    total = q.count()
    items = q.order_by(Regulation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return RegulationListOut(items=items, total=total)


@router.get("/{regulation_id}", response_model=RegulationDetailOut)
def get_regulation(
    regulation_id: int,
    current_user: User = Depends(require_permission(PERM_REGULATION_VIEW)),
    db: Session = Depends(get_db),
):
    """获取制度详情（含修改历史，需查看制度权限）"""
    reg = db.query(Regulation).filter(Regulation.id == regulation_id).first()
    if not reg:
        raise HTTPException(404, "制度不存在")
    return reg


@router.post("", response_model=RegulationOut)
def create_regulation(
    data: RegulationCreate,
    request: Request,
    current_user: User = Depends(require_permission(PERM_REGULATION_CREATE)),
    db: Session = Depends(get_db),
):
    """新增制度（需新增制度权限，版本号自动生成 V01_{类别代码}_{年月日}）"""
    editor = current_user.name or current_user.employee_id

    # 查找类别名称和代码
    cat = None
    if data.category_id:
        cat = db.query(RegulationCategory).filter(RegulationCategory.id == data.category_id).first()
    cat_name = cat.name if cat else (data.category_name or None)
    cat_code = (cat.code if cat and cat.code else "XXX")

    reg = Regulation(
        name=data.name,
        category_id=data.category_id,
        category_name=cat_name,
        content=data.content,
        created_by=editor,
        updated_by=editor,
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)

    # [新增] 自动生成版本号：V01_{类别代码}_{年月日}
    version = f"V01_{cat_code}_{utc_now().strftime('%y%m%d')}"
    reg.version = version

    # [新增] 记录初始版本历史（含内容快照）
    db.add(_record_history(reg, version, reg.content or '', editor))
    db.commit()

    # [改进/A2] 制度新增留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "regulation_create", current_user.employee_id,
                     detail=f"name={reg.name} version={version}", target=str(reg.id), ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    # [新增 2026-09-15] 补发站内信（事件：regulation.changed）
    _notify_regulation_change(
        db, current_user, f"制度「{reg.name}」",
        f"新增了制度「{reg.name}」（版本 {version}）",
    )
    return reg


@router.put("/{regulation_id}", response_model=RegulationOut)
def update_regulation(
    regulation_id: int,
    data: RegulationUpdate,
    request: Request,
    current_user: User = Depends(require_permission(PERM_REGULATION_EDIT)),
    db: Session = Depends(get_db),
):
    """修改制度（需编辑制度权限；版本号自动递增，每次修改创建历史版本含内容快照）"""
    reg = db.query(Regulation).filter(Regulation.id == regulation_id).first()
    if not reg:
        raise HTTPException(404, "制度不存在")

    editor = current_user.name or current_user.employee_id

    # 记录修改摘要
    changes = []
    if data.name is not None and data.name != reg.name:
        changes.append(f"制度名称: {reg.name} → {data.name}")
    if data.content is not None and data.content != reg.content:
        changes.append("制度内容已更新")
    if data.category_id is not None and data.category_id != reg.category_id:
        changes.append("所属类别已变更")

    if data.category_id is not None and not data.category_name:
        cat = db.query(RegulationCategory).filter(RegulationCategory.id == data.category_id).first()
        if cat:
            data.category_name = cat.name

    # 更新字段
    if data.name is not None:
        reg.name = data.name
    if data.category_id is not None:
        reg.category_id = data.category_id
    if data.category_name is not None:
        reg.category_name = data.category_name
    if data.content is not None:
        reg.content = data.content
    reg.updated_by = editor

    # [新增] 自动生成递增版本号
    cat = db.query(RegulationCategory).filter(RegulationCategory.id == reg.category_id).first()
    cat_code = (cat.code if cat and cat.code else "XXX")
    new_version = _gen_version(reg, cat_code)
    reg.version = new_version

    # [改进] 每次修改创建版本历史记录（含版本号+内容快照）
    db.add(_record_history(reg, new_version, reg.content or '', editor,
                           change_summary="；".join(changes) if changes else ""))

    db.commit()
    db.refresh(reg)

    # [修复 2026-09-01] 制度编辑留痕（原先完全缺失）
    if changes:
        try:
            client_ip = get_client_ip(request)
            changes_str = "；".join(changes)
            record_audit(db, "regulation_update", current_user.employee_id,
                         detail=f"name={reg.name} version={new_version} changes={changes_str}",
                         target=str(regulation_id), ip_address=client_ip)
            db.commit()
        except Exception:
            db.rollback()
        # [新增 2026-09-15] 补发站内信（事件：regulation.changed；仅在字段确有变化时发送）
        _notify_regulation_change(
            db, current_user, f"制度「{reg.name}」",
            "修改了制度「{}」（版本 {}）：{}".format(reg.name, new_version, "；".join(changes)),
        )
    return reg


@router.get("/{regulation_id}/history", response_model=list[RegulationHistoryOut])
def get_regulation_history(
    regulation_id: int,
    current_user: User = Depends(require_permission(PERM_REGULATION_VIEW)),
    db: Session = Depends(get_db),
):
    """[新增] 获取制度历史版本列表（按时间倒序，不含完整内容）"""
    reg = db.query(Regulation).filter(Regulation.id == regulation_id).first()
    if not reg:
        raise HTTPException(404, "制度不存在")
    return db.query(RegulationHistory).filter(
        RegulationHistory.regulation_id == regulation_id,
    ).order_by(RegulationHistory.edited_at.desc()).all()


@router.get("/{regulation_id}/history/{history_id}", response_model=RegulationHistoryDetailOut)
def get_regulation_history_detail(
    regulation_id: int,
    history_id: int,
    current_user: User = Depends(require_permission(PERM_REGULATION_VIEW)),
    db: Session = Depends(get_db),
):
    """[新增] 获取历史版本详情（含该版本的完整制度内容快照）"""
    h = db.query(RegulationHistory).filter(
        RegulationHistory.id == history_id,
        RegulationHistory.regulation_id == regulation_id,
    ).first()
    if not h:
        raise HTTPException(404, "历史版本不存在")
    return h


@router.delete("/{regulation_id}")
def delete_regulation(
    regulation_id: int,
    request: Request,
    current_user: User = Depends(require_permission(PERM_REGULATION_DELETE)),
    db: Session = Depends(get_db),
):
    """删除制度（需删除制度权限）"""
    reg = db.query(Regulation).filter(Regulation.id == regulation_id).first()
    if not reg:
        raise HTTPException(404, "制度不存在")
    reg_name = reg.name
    db.delete(reg)
    db.commit()
    # [改进/A2] 制度删除留痕
    try:
        client_ip = get_client_ip(request)
        record_audit(db, "regulation_delete", current_user.employee_id,
                     detail=f"name={reg_name}", target=str(regulation_id), ip_address=client_ip)
        db.commit()
    except Exception:
        db.rollback()
    # [新增 2026-09-15] 补发站内信（事件：regulation.changed）
    _notify_regulation_change(db, current_user, f"制度「{reg_name}」", f"删除了制度「{reg_name}」")
    return {"message": "删除成功"}
