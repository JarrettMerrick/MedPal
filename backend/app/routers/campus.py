# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""
院区-楼栋-楼层-区域 路由模块
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, has_permission, PERM_SIGNAGE_CAMPUS
from app.models.user import User
from app.schemas.campus import (
    CampusCreate, CampusUpdate, CampusOut,
    BuildingCreate, BuildingUpdate, BuildingOut,
    FloorCreate, FloorUpdate, FloorOut,
    AreaCreate, AreaUpdate, AreaOut,
    CampusTreeNode,
)
from app.services.campus_service import (
    get_campus, get_campus_by_name, get_all_campuses, get_campuses,
    create_campus, update_campus, delete_campus,
    get_building, get_buildings_by_campus, get_buildings,
    create_building, update_building, delete_building,
    get_floor, get_floors_by_building, get_floors,
    create_floor, update_floor, delete_floor,
    get_area, get_areas_by_floor, get_areas,
    create_area, update_area, delete_area,
    get_campus_tree, validate_campus_hierarchy,
)
# [新增 2026-09-09] 空间结构写操作审计留痕 + 统一 IP 获取
from app.services.audit_service import record_audit
# [新增 2026-09-15] 站内信提醒：院区 / 楼栋 / 楼层 / 区域变更后通知管理方
from app.services.modification_notify import notify_super_admins
from app.utils import get_client_ip
from fastapi import Request

router = APIRouter(prefix="/api/campus", tags=["院区管理"])


def _audit(db, action, current_user, target, detail, request):
    """[新增 2026-09-09] 院区/楼宇/楼层/区域写操作审计留痕（失败静默，不影响主流程）"""
    try:
        client_ip = get_client_ip(request)
        record_audit(db, action, current_user.employee_id, detail=detail,
                     target=str(target), ip_address=client_ip)
        db.commit()
    except Exception:
        pass

    # [新增 2026-09-15] 空间结构变更后补发站内信（事件：院区 / 楼栋 / 楼层 / 区域变更）：
    # 在 _audit 内统一发送，一次覆盖全部 12 个写端点（创建/更新/删除 × 院区/楼栋/楼层/区域）。
    # 院区结构是标识牌定位与筛选的基础数据，改动会影响所有标识的归属与统计口径，
    # 此前只留痕不提醒，管理方无从察觉。失败静默，不影响主流程。
    try:
        _ACTION_LABELS = {
            "campus_create": "新增院区", "campus_update": "修改院区", "campus_delete": "删除院区",
            "building_create": "新增楼栋", "building_update": "修改楼栋", "building_delete": "删除楼栋",
            "floor_create": "新增楼层", "floor_update": "修改楼层", "floor_delete": "删除楼层",
            "area_create": "新增区域", "area_update": "修改区域", "area_delete": "删除区域",
        }
        action_label = _ACTION_LABELS.get(action, action)
        # detail 形如 "name=门诊楼" / "number=3" / "type=merged"：去掉字段名前缀便于阅读
        detail_text = detail or ""
        for _prefix in ("name=", "number=", "type="):
            detail_text = detail_text.replace(_prefix, "")
        obj_desc = f"「{detail_text}」" if detail_text else ""

        mod_user = db.query(User).filter(User.employee_id == current_user.employee_id).first()
        modifier_name = mod_user.name if mod_user else current_user.employee_id
        notify_super_admins(
            db,
            title=f"院区结构变更：{action_label}",
            content=f"{modifier_name} {action_label}{obj_desc}",
            related_type="campus",
            exclude_user_id=current_user.employee_id,
            event_code="campus.changed",
            context={
                "操作人": modifier_name,
                "对象": detail_text or f"ID {target}",
                "变更内容": action_label,
            },
        )
        db.commit()
    except Exception:
        pass


# ==================== 院区接口 ====================

@router.get("", response_model=dict)
def list_campuses(
    page: int = Query(1, ge=1),
    # [修复 2026-09-08] 放宽 page_size 上限至 500，与其他 campus 列表端点口径一致
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取院区列表"""
    campuses, total = get_campuses(db, page, page_size, search)
    
    # 转换为输出格式，包含楼栋数量
    items = []
    for campus in campuses:
        building_count = len(get_buildings_by_campus(db, campus.id))
        item = CampusOut.model_validate(campus)
        item.building_count = building_count
        items.append(item)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/all")
def list_all_campuses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有启用的院区"""
    campuses = get_all_campuses(db, active_only=True)
    return [{"id": c.id, "name": c.name} for c in campuses]


@router.get("/tree")
def get_campus_tree_api(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取院区-楼栋-楼层-区域树形结构"""
    return get_campus_tree(db)


@router.get("/{campus_id}", response_model=CampusOut)
def get_campus_detail(
    campus_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取院区详情"""
    campus = get_campus(db, campus_id)
    if not campus:
        raise HTTPException(status_code=404, detail="院区不存在")
    
    building_count = len(get_buildings_by_campus(db, campus.id))
    result = CampusOut.model_validate(campus)
    result.building_count = building_count
    return result


@router.post("", response_model=CampusOut, status_code=201)
def create_campus_api(
    req: CampusCreate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建院区"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限创建院区")
    
    # 检查名称是否已存在
    existing = get_campus_by_name(db, req.name)
    if existing:
        raise HTTPException(status_code=400, detail="院区名称已存在")
    
    campus = create_campus(db, req, created_by=current_user.employee_id)
    # [新增 2026-09-09] 院区创建审计留痕
    _audit(db, "campus_create", current_user, campus.id, f"name={campus.name}", request)
    return CampusOut.model_validate(campus)


@router.put("/{campus_id}", response_model=CampusOut)
def update_campus_api(
    campus_id: int,
    req: CampusUpdate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新院区"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限编辑院区")
    
    # 检查院区是否存在
    campus = get_campus(db, campus_id)
    if not campus:
        raise HTTPException(status_code=404, detail="院区不存在")
    
    # 检查名称是否已被其他院区使用
    if req.name and req.name != campus.name:
        existing = get_campus_by_name(db, req.name)
        if existing:
            raise HTTPException(status_code=400, detail="院区名称已存在")
    
    updated_campus = update_campus(db, campus_id, req, updated_by=current_user.employee_id)
    if not updated_campus:
        raise HTTPException(status_code=500, detail="更新院区失败")
    
    # [新增 2026-09-09] 院区更新审计留痕
    _audit(db, "campus_update", current_user, campus_id, f"name={updated_campus.name}", request)
    return CampusOut.model_validate(updated_campus)


@router.delete("/{campus_id}")
def delete_campus_api(
    campus_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除院区"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限删除院区")
    
    # 检查院区是否存在
    campus = get_campus(db, campus_id)
    if not campus:
        raise HTTPException(status_code=404, detail="院区不存在")
    
    # 检查是否有关联的楼栋
    buildings = get_buildings_by_campus(db, campus_id, active_only=False)
    if buildings:
        raise HTTPException(status_code=400, detail="该院区下仍有楼栋，无法删除")
    
    success = delete_campus(db, campus_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除院区失败")
    
    # [新增 2026-09-09] 院区删除审计留痕
    _audit(db, "campus_delete", current_user, campus_id, f"name={campus.name}", request)
    return {"message": "删除成功"}


# ==================== 楼栋接口 ====================

@router.get("/{campus_id}/buildings")
def list_buildings(
    campus_id: int,
    page: int = Query(1, ge=1),
    # [修复 2026-09-08] 放宽 page_size 上限至 500：筛选栏一次性拉取楼栋（page_size=200）
    # 超出原上限 100 会被 422 拦截，前端静默容错后表现为"楼栋下拉无数据"
    page_size: int = Query(20, ge=1, le=500),
    search: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取院区下的楼栋列表"""
    # 检查院区是否存在
    campus = get_campus(db, campus_id)
    if not campus:
        raise HTTPException(status_code=404, detail="院区不存在")
    
    buildings, total = get_buildings(db, page, page_size, search, campus_id)
    
    # 转换为输出格式，包含楼层数量
    items = []
    for building in buildings:
        floor_count = len(get_floors_by_building(db, building.id))
        item = BuildingOut.model_validate(building)
        item.campus_name = campus.name
        item.floor_count = floor_count
        items.append(item)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/buildings/{building_id}", response_model=BuildingOut)
def get_building_detail(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取楼栋详情"""
    building = get_building(db, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    campus = get_campus(db, building.campus_id)
    floor_count = len(get_floors_by_building(db, building.id))
    
    result = BuildingOut.model_validate(building)
    result.campus_name = campus.name if campus else None
    result.floor_count = floor_count
    return result


@router.post("/buildings", response_model=BuildingOut, status_code=201)
def create_building_api(
    req: BuildingCreate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建楼栋"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限创建楼栋")
    
    # 校验层级关系
    valid, msg = validate_campus_hierarchy(db, campus_id=req.campus_id)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    
    # 检查楼栋编号在院区内是否唯一
    existing_buildings = get_buildings_by_campus(db, req.campus_id, active_only=False)
    for building in existing_buildings:
        if building.building_number == req.building_number:
            raise HTTPException(status_code=400, detail="楼栋编号在院区内已存在")
    
    building = create_building(db, req, created_by=current_user.employee_id)
    # [新增 2026-09-09] 楼栋创建审计留痕
    _audit(db, "building_create", current_user, building.id, f"number={building.building_number}", request)
    return BuildingOut.model_validate(building)


@router.put("/buildings/{building_id}", response_model=BuildingOut)
def update_building_api(
    building_id: int,
    req: BuildingUpdate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新楼栋"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限编辑楼栋")
    
    # 检查楼栋是否存在
    building = get_building(db, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    # 校验层级关系
    campus_id = req.campus_id if req.campus_id is not None else building.campus_id
    valid, msg = validate_campus_hierarchy(db, campus_id=campus_id)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    
    # 检查楼栋编号在院区内是否唯一（排除自身）
    if req.building_number and req.building_number != building.building_number:
        existing_buildings = get_buildings_by_campus(db, campus_id, active_only=False)
        for b in existing_buildings:
            if b.id != building_id and b.building_number == req.building_number:
                raise HTTPException(status_code=400, detail="楼栋编号在院区内已存在")
    
    updated_building = update_building(db, building_id, req, updated_by=current_user.employee_id)
    if not updated_building:
        raise HTTPException(status_code=500, detail="更新楼栋失败")
    
    # [新增 2026-09-09] 楼栋更新审计留痕
    _audit(db, "building_update", current_user, building_id, f"number={updated_building.building_number}", request)
    return BuildingOut.model_validate(updated_building)


@router.delete("/buildings/{building_id}")
def delete_building_api(
    building_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除楼栋"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限删除楼栋")
    
    # 检查楼栋是否存在
    building = get_building(db, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    # 检查是否有关联的楼层
    floors = get_floors_by_building(db, building_id, active_only=False)
    if floors:
        raise HTTPException(status_code=400, detail="该楼栋下仍有楼层，无法删除")
    
    success = delete_building(db, building_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除楼栋失败")
    
    # [新增 2026-09-09] 楼栋删除审计留痕
    _audit(db, "building_delete", current_user, building_id, f"number={building.building_number}", request)
    return {"message": "删除成功"}


# ==================== 楼层接口 ====================

@router.get("/buildings/{building_id}/floors")
def list_floors(
    building_id: int,
    page: int = Query(1, ge=1),
    # [修复 2026-09-08] 放宽 page_size 上限至 500：筛选栏一次性拉取楼层（page_size=200），
    # 超出原上限 100 会被 422 拦截，前端静默容错后表现为"楼层下拉无数据"
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取楼栋下的楼层列表"""
    # 检查楼栋是否存在
    building = get_building(db, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    floors, total = get_floors(db, page, page_size, building_id)
    
    # 转换为输出格式，包含区域数量和层级信息
    items = []
    for floor in floors:
        area_count = len(get_areas_by_floor(db, floor.id))
        item = FloorOut.model_validate(floor)
        item.building_name = building.name
        item.campus_id = building.campus_id
        
        campus = get_campus(db, building.campus_id)
        item.campus_name = campus.name if campus else None
        item.area_count = area_count
        items.append(item)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/floors/{floor_id}", response_model=FloorOut)
def get_floor_detail(
    floor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取楼层详情"""
    floor = get_floor(db, floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="楼层不存在")
    
    building = get_building(db, floor.building_id)
    campus = get_campus(db, building.campus_id) if building else None
    area_count = len(get_areas_by_floor(db, floor.id))
    
    result = FloorOut.model_validate(floor)
    result.building_name = building.name if building else None
    result.campus_id = building.campus_id if building else None
    result.campus_name = campus.name if campus else None
    result.area_count = area_count
    return result


@router.post("/floors", response_model=FloorOut, status_code=201)
def create_floor_api(
    req: FloorCreate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建楼层"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限创建楼层")
    
    # 校验层级关系
    building = get_building(db, req.building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    valid, msg = validate_campus_hierarchy(db, building_id=req.building_id)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    
    # 检查楼层号在楼栋内是否唯一
    existing_floors = get_floors_by_building(db, req.building_id, active_only=False)
    for floor in existing_floors:
        if floor.floor_number == req.floor_number:
            raise HTTPException(status_code=400, detail="楼层号在楼栋内已存在")
    
    floor = create_floor(db, req, created_by=current_user.employee_id)
    
    # [新增 2026-09-09] 楼层创建审计留痕
    _audit(db, "floor_create", current_user, floor.id, f"number={floor.floor_number}", request)
    # 返回完整信息
    result = FloorOut.model_validate(floor)
    result.building_name = building.name
    result.campus_id = building.campus_id
    campus = get_campus(db, building.campus_id)
    result.campus_name = campus.name if campus else None
    return result


@router.put("/floors/{floor_id}", response_model=FloorOut)
def update_floor_api(
    floor_id: int,
    req: FloorUpdate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新楼层"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限编辑楼层")
    
    # 检查楼层是否存在
    floor = get_floor(db, floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="楼层不存在")
    
    # 校验层级关系
    building_id = req.building_id if req.building_id is not None else floor.building_id
    building = get_building(db, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    valid, msg = validate_campus_hierarchy(db, building_id=building_id)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    
    # 检查楼层号在楼栋内是否唯一（排除自身）
    if req.floor_number and req.floor_number != floor.floor_number:
        existing_floors = get_floors_by_building(db, building_id, active_only=False)
        for f in existing_floors:
            if f.id != floor_id and f.floor_number == req.floor_number:
                raise HTTPException(status_code=400, detail="楼层号在楼栋内已存在")
    
    updated_floor = update_floor(db, floor_id, req, updated_by=current_user.employee_id)
    if not updated_floor:
        raise HTTPException(status_code=500, detail="更新楼层失败")
    
    # [新增 2026-09-09] 楼层更新审计留痕
    _audit(db, "floor_update", current_user, floor_id, f"number={updated_floor.floor_number}", request)
    # 返回完整信息
    result = FloorOut.model_validate(updated_floor)
    result.building_name = building.name
    result.campus_id = building.campus_id
    campus = get_campus(db, building.campus_id)
    result.campus_name = campus.name if campus else None
    return result


@router.delete("/floors/{floor_id}")
def delete_floor_api(
    floor_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除楼层"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限删除楼层")
    
    # 检查楼层是否存在
    floor = get_floor(db, floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="楼层不存在")
    
    # 检查是否有关联的区域
    areas = get_areas_by_floor(db, floor_id, active_only=False)
    if areas:
        raise HTTPException(status_code=400, detail="该楼层下仍有区域，无法删除")
    
    success = delete_floor(db, floor_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除楼层失败")
    
    # [新增 2026-09-09] 楼层删除审计留痕
    _audit(db, "floor_delete", current_user, floor_id, f"number={floor.floor_number}", request)
    return {"message": "删除成功"}


# ==================== 区域接口 ====================

@router.get("/floors/{floor_id}/areas")
def list_areas(
    floor_id: int,
    page: int = Query(1, ge=1),
    # [修复 2026-09-08] 放宽 page_size 上限至 500，与其他 campus 列表端点口径一致
    page_size: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取楼层下的区域列表"""
    # 检查楼层是否存在
    floor = get_floor(db, floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="楼层不存在")
    
    areas, total = get_areas(db, page, page_size, floor_id)
    
    # 转换为输出格式，包含层级信息
    building = get_building(db, floor.building_id)
    campus = get_campus(db, building.campus_id) if building else None
    
    items = []
    for area in areas:
        item = AreaOut.model_validate(area)
        item.floor_name = floor.floor_name
        item.building_id = building.id if building else None
        item.building_name = building.name if building else None
        item.campus_id = building.campus_id if building else None
        item.campus_name = campus.name if campus else None
        items.append(item)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/areas/{area_id}", response_model=AreaOut)
def get_area_detail(
    area_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取区域详情"""
    area = get_area(db, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="区域不存在")
    
    floor = get_floor(db, area.floor_id)
    building = get_building(db, floor.building_id) if floor else None
    campus = get_campus(db, building.campus_id) if building else None
    
    result = AreaOut.model_validate(area)
    result.floor_name = floor.floor_name if floor else None
    result.building_id = building.id if building else None
    result.building_name = building.name if building else None
    result.campus_id = building.campus_id if building else None
    result.campus_name = campus.name if campus else None
    return result


@router.post("/areas", response_model=AreaOut, status_code=201)
def create_area_api(
    req: AreaCreate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建区域"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限创建区域")
    
    # 校验层级关系
    floor = get_floor(db, req.floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="楼层不存在")
    
    building = get_building(db, floor.building_id)
    if not building:
        raise HTTPException(status_code=404, detail="楼栋不存在")
    
    valid, msg = validate_campus_hierarchy(db, floor_id=req.floor_id)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    
    # [调整 2026-09-12] 取消「一个楼层仅限一个区域」与区域类型互斥限制：
    # 同一楼层现可自由划分并绑定多个区域（例如东区可关联多个区域），
    # area_type（east/west/merged）仅作为分类标签，不再做唯一性校验。
    # 原实现的两条限制已移除：
    #   1) 非 merged 类型在同一楼层不可重复（导致同层不能有多个「东区」）；
    #   2) 楼层已存在 merged 区域时禁止再新增（导致同层只能有一个区域）。

    area = create_area(db, req, created_by=current_user.employee_id)
    
    # [新增 2026-09-09] 区域创建审计留痕
    _audit(db, "area_create", current_user, area.id, f"type={area.area_type}", request)
    # 返回完整信息
    result = AreaOut.model_validate(area)
    result.floor_name = floor.floor_name
    result.building_id = building.id
    result.building_name = building.name
    result.campus_id = building.campus_id
    campus = get_campus(db, building.campus_id)
    result.campus_name = campus.name if campus else None
    return result


@router.put("/areas/{area_id}", response_model=AreaOut)
def update_area_api(
    area_id: int,
    req: AreaUpdate,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新区域"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限编辑区域")
    
    # 检查区域是否存在
    area = get_area(db, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="区域不存在")
    
    # 校验层级关系
    floor_id = req.floor_id if req.floor_id is not None else area.floor_id
    floor = get_floor(db, floor_id)
    if not floor:
        raise HTTPException(status_code=404, detail="楼层不存在")
    
    valid, msg = validate_campus_hierarchy(db, floor_id=floor_id)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
    
    # [调整 2026-09-12] 同步取消更新时的区域类型互斥限制（与创建接口保持一致）：
    # 允许同一楼层存在多个区域，且区域类型可自由调整。

    updated_area = update_area(db, area_id, req, updated_by=current_user.employee_id)
    if not updated_area:
        raise HTTPException(status_code=500, detail="更新区域失败")
    
    # [新增 2026-09-09] 区域更新审计留痕
    _audit(db, "area_update", current_user, area_id, f"type={updated_area.area_type}", request)
    # 返回完整信息
    result = AreaOut.model_validate(updated_area)
    result.floor_name = floor.floor_name
    building = get_building(db, floor.building_id)
    result.building_id = building.id if building else None
    result.building_name = building.name if building else None
    result.campus_id = building.campus_id if building else None
    campus = get_campus(db, building.campus_id) if building else None
    result.campus_name = campus.name if campus else None
    return result


@router.delete("/areas/{area_id}")
def delete_area_api(
    area_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除区域"""
    # 检查权限
    if not has_permission(current_user, PERM_SIGNAGE_CAMPUS):
        raise HTTPException(status_code=403, detail="无权限删除区域")
    
    # 检查区域是否存在
    area = get_area(db, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="区域不存在")
    
    success = delete_area(db, area_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除区域失败")
    
    # [新增 2026-09-09] 区域删除审计留痕
    _audit(db, "area_delete", current_user, area_id, f"type={area.area_type}", request)
    return {"message": "删除成功"}