# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""
院区-楼栋-楼层-区域 业务逻辑层
"""

from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, case, cast, Integer

from app.models.campus import Campus, Building, Floor, Area
from app.schemas.campus import (
    CampusCreate, CampusUpdate, CampusOut,
    BuildingCreate, BuildingUpdate, BuildingOut,
    FloorCreate, FloorUpdate, FloorOut,
    AreaCreate, AreaUpdate, AreaOut,
    CampusTreeNode, BuildingTreeNode, FloorTreeNode, AreaTreeNode
)


def floor_order_expr():
    """楼层号排序表达式：[新增 2026-09-17] 适配字母编号（F1/F2…、B1/B2…）。

    排序口径（与前端 utils/floor.ts 的 floorSortValue 一致）：
        B3 < B2 < B1 < F1 < F2 < F3 …
    即地下层在前、越深越靠前；地上层按层数升序。

    实现：截取第 2 个字符起的数字部分（B1 → 1），地下前缀取负（B1 → -1）。
    另兼容迁移前的旧编号：旧库中地下层为负数文本（如 "-1"），同样按地下层取负，
    即使迁移尚未执行（或手工写入旧值）也不会出现排序错乱。
    历史遗留的其它非规范值截取为空串，SQLite 将 CAST('' AS INTEGER) 视作 0，不会报错。
    """
    number_part = cast(func.substr(Floor.floor_number, 2), Integer)
    return case(
        # B1/B2…：地下层，B1 → -1
        (Floor.floor_number.like("B%"), -number_part),
        # 旧格式负数（"−1" 表示地下一层）：迁移前的过渡兼容
        (Floor.floor_number.like("-%"), -number_part),
        else_=number_part,
    )


# ==================== 院区 CRUD ====================

def get_campus(db: Session, campus_id: int) -> Optional[Campus]:
    """获取单个院区"""
    return db.query(Campus).filter(Campus.id == campus_id).first()


def get_campus_by_name(db: Session, name: str) -> Optional[Campus]:
    """根据名称获取院区"""
    return db.query(Campus).filter(Campus.name == name).first()


def get_all_campuses(db: Session, active_only: bool = True) -> List[Campus]:
    """获取所有院区"""
    query = db.query(Campus)
    if active_only:
        query = query.filter(Campus.is_active == True)
    return query.order_by(Campus.name).all()


def get_campuses(db: Session, page: int = 1, page_size: int = 20, search: str = None) -> Tuple[List[Campus], int]:
    """分页获取院区列表"""
    query = db.query(Campus)
    
    if search:
        query = query.filter(Campus.name.contains(search))
    
    total = query.count()
    campuses = query.order_by(Campus.name).offset((page - 1) * page_size).limit(page_size).all()
    
    return campuses, total


def create_campus(db: Session, campus_data: CampusCreate, created_by: str = None) -> Campus:
    """创建院区"""
    campus = Campus(
        name=campus_data.name,
        description=campus_data.description,
        address=campus_data.address,
        code=campus_data.code,
        is_active=campus_data.is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(campus)
    db.commit()
    db.refresh(campus)
    return campus


def update_campus(db: Session, campus_id: int, campus_data: CampusUpdate, updated_by: str = None) -> Optional[Campus]:
    """更新院区"""
    campus = get_campus(db, campus_id)
    if not campus:
        return None
    
    update_data = campus_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(campus, key, value)
    
    campus.updated_by = updated_by
    db.commit()
    db.refresh(campus)
    return campus


def delete_campus(db: Session, campus_id: int) -> bool:
    """删除院区"""
    campus = get_campus(db, campus_id)
    if not campus:
        return False
    
    db.delete(campus)
    db.commit()
    return True


# ==================== 楼栋 CRUD ====================

def get_building(db: Session, building_id: int) -> Optional[Building]:
    """获取单个楼栋"""
    return db.query(Building).filter(Building.id == building_id).first()


def get_buildings_by_campus(db: Session, campus_id: int, active_only: bool = True) -> List[Building]:
    """获取院区下的所有楼栋"""
    query = db.query(Building).filter(Building.campus_id == campus_id)
    if active_only:
        query = query.filter(Building.is_active == True)
    return query.order_by(Building.building_number).all()


def get_buildings(db: Session, page: int = 1, page_size: int = 20, search: str = None, campus_id: int = None) -> Tuple[List[Building], int]:
    """分页获取楼栋列表"""
    query = db.query(Building)
    
    if search:
        query = query.filter(
            (Building.name.contains(search)) | 
            (Building.building_number.contains(search))
        )
    
    if campus_id:
        query = query.filter(Building.campus_id == campus_id)
    
    total = query.count()
    buildings = query.order_by(Building.building_number).offset((page - 1) * page_size).limit(page_size).all()
    
    return buildings, total


def create_building(db: Session, building_data: BuildingCreate, created_by: str = None) -> Building:
    """创建楼栋"""
    building = Building(
        campus_id=building_data.campus_id,
        name=building_data.name,
        building_number=building_data.building_number,
        description=building_data.description,
        is_active=building_data.is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


def update_building(db: Session, building_id: int, building_data: BuildingUpdate, updated_by: str = None) -> Optional[Building]:
    """更新楼栋"""
    building = get_building(db, building_id)
    if not building:
        return None
    
    update_data = building_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(building, key, value)
    
    building.updated_by = updated_by
    db.commit()
    db.refresh(building)
    return building


def delete_building(db: Session, building_id: int) -> bool:
    """删除楼栋"""
    building = get_building(db, building_id)
    if not building:
        return False
    
    db.delete(building)
    db.commit()
    return True


# ==================== 楼层 CRUD ====================

def get_floor(db: Session, floor_id: int) -> Optional[Floor]:
    """获取单个楼层"""
    return db.query(Floor).filter(Floor.id == floor_id).first()


def get_floors_by_building(db: Session, building_id: int, active_only: bool = True) -> List[Floor]:
    """获取楼栋下的所有楼层"""
    query = db.query(Floor).filter(Floor.building_id == building_id)
    if active_only:
        query = query.filter(Floor.is_active == True)
    return query.order_by(floor_order_expr()).all()


def get_floors(db: Session, page: int = 1, page_size: int = 20, building_id: int = None) -> Tuple[List[Floor], int]:
    """分页获取楼层列表"""
    query = db.query(Floor)
    
    if building_id:
        query = query.filter(Floor.building_id == building_id)
    
    total = query.count()
    floors = query.order_by(floor_order_expr()).offset((page - 1) * page_size).limit(page_size).all()
    
    return floors, total


def create_floor(db: Session, floor_data: FloorCreate, created_by: str = None) -> Floor:
    """创建楼层"""
    floor = Floor(
        building_id=floor_data.building_id,
        floor_number=floor_data.floor_number,
        floor_name=floor_data.floor_name,
        description=floor_data.description,
        is_active=floor_data.is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(floor)
    db.commit()
    db.refresh(floor)
    return floor


def update_floor(db: Session, floor_id: int, floor_data: FloorUpdate, updated_by: str = None) -> Optional[Floor]:
    """更新楼层"""
    floor = get_floor(db, floor_id)
    if not floor:
        return None
    
    update_data = floor_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(floor, key, value)
    
    floor.updated_by = updated_by
    db.commit()
    db.refresh(floor)
    return floor


def delete_floor(db: Session, floor_id: int) -> bool:
    """删除楼层"""
    floor = get_floor(db, floor_id)
    if not floor:
        return False
    
    db.delete(floor)
    db.commit()
    return True


# ==================== 区域 CRUD ====================

def get_area(db: Session, area_id: int) -> Optional[Area]:
    """获取单个区域"""
    return db.query(Area).filter(Area.id == area_id).first()


def get_areas_by_floor(db: Session, floor_id: int, active_only: bool = True) -> List[Area]:
    """获取楼层下的所有区域"""
    query = db.query(Area).filter(Area.floor_id == floor_id)
    if active_only:
        query = query.filter(Area.is_active == True)
    return query.order_by(Area.name).all()


def get_areas(db: Session, page: int = 1, page_size: int = 20, floor_id: int = None) -> Tuple[List[Area], int]:
    """分页获取区域列表"""
    query = db.query(Area)
    
    if floor_id:
        query = query.filter(Area.floor_id == floor_id)
    
    total = query.count()
    areas = query.order_by(Area.name).offset((page - 1) * page_size).limit(page_size).all()
    
    return areas, total


def create_area(db: Session, area_data: AreaCreate, created_by: str = None) -> Area:
    """创建区域"""
    area = Area(
        floor_id=area_data.floor_id,
        name=area_data.name,
        area_type=area_data.area_type,
        description=area_data.description,
        is_active=area_data.is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


def update_area(db: Session, area_id: int, area_data: AreaUpdate, updated_by: str = None) -> Optional[Area]:
    """更新区域"""
    area = get_area(db, area_id)
    if not area:
        return None
    
    update_data = area_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(area, key, value)
    
    area.updated_by = updated_by
    db.commit()
    db.refresh(area)
    return area


def delete_area(db: Session, area_id: int) -> bool:
    """删除区域"""
    area = get_area(db, area_id)
    if not area:
        return False
    
    db.delete(area)
    db.commit()
    return True


# ==================== 层级结构 ====================

def get_campus_tree(db: Session) -> List[CampusTreeNode]:
    """获取院区-楼栋-楼层-区域树形结构"""
    campuses = db.query(Campus).filter(Campus.is_active == True).order_by(Campus.name).all()
    
    result = []
    for campus in campuses:
        # 获取院区下的楼栋
        buildings = db.query(Building).filter(
            Building.campus_id == campus.id,
            Building.is_active == True
        ).order_by(Building.building_number).all()
        
        building_nodes = []
        for building in buildings:
            # 获取楼栋下的楼层
            floors = db.query(Floor).filter(
                Floor.building_id == building.id,
                Floor.is_active == True
            ).order_by(floor_order_expr()).all()
            
            floor_nodes = []
            for floor in floors:
                # 获取楼层下的区域
                areas = db.query(Area).filter(
                    Area.floor_id == floor.id,
                    Area.is_active == True
                ).order_by(Area.name).all()
                
                area_nodes = [
                    AreaTreeNode(
                        id=area.id,
                        name=area.name,
                        area_type=area.area_type,
                    )
                    for area in areas
                ]
                
                floor_nodes.append(FloorTreeNode(
                    id=floor.id,
                    floor_number=floor.floor_number,
                    floor_name=floor.floor_name,
                    children=area_nodes,
                ))
            
            building_nodes.append(BuildingTreeNode(
                id=building.id,
                name=building.name,
                building_number=building.building_number,
                children=floor_nodes,
            ))
        
        result.append(CampusTreeNode(
            id=campus.id,
            name=campus.name,
            children=building_nodes,
        ))
    
    return result


def validate_campus_hierarchy(db: Session, campus_id: int = None, building_id: int = None, floor_id: int = None) -> Tuple[bool, str]:
    """校验层级关系"""
    if campus_id:
        campus = get_campus(db, campus_id)
        if not campus:
            return False, "院区不存在"
        if not campus.is_active:
            return False, "院区已禁用"
    
    if building_id:
        building = get_building(db, building_id)
        if not building:
            return False, "楼栋不存在"
        if not building.is_active:
            return False, "楼栋已禁用"
        if campus_id and building.campus_id != campus_id:
            return False, "楼栋不属于指定院区"
    
    if floor_id:
        floor = get_floor(db, floor_id)
        if not floor:
            return False, "楼层不存在"
        if not floor.is_active:
            return False, "楼层已禁用"
        if building_id and floor.building_id != building_id:
            return False, "楼层不属于指定楼栋"
    
    return True, "校验通过"