import logging
from sqlalchemy.orm import Session
from app.models.signage import Signage
from app.services.signage_service import create_signage

logger = logging.getLogger("hospital")

def batch_generate_door_signs(db, building, floor, room_numbers, oa_number, created_by):
    """[新增 2026-09-03] 批量生成门牌标识"""
    created = []
    for room in room_numbers:
        data = {"name": f"{room}门牌", "category": "科室门牌", "building": building, "floor": floor, "location_desc": f"{building}{floor}{room}"}
        s = create_signage(db, data, created_by)
        created.append(s)
    db.commit()
    return created

def batch_update_department(db, old_dept, new_dept, oa_number, updated_by):
    """[新增 2026-09-03] 批量更新关联科室"""
    items = db.query(Signage).filter(Signage.location_desc.like(f"%{old_dept}%")).all()
    from app.services.signage_service import update_signage
    updated = []
    for s in items:
        update_signage(db, s.id, {"location_desc": s.location_desc.replace(old_dept, new_dept)}, updated_by, oa_number)
        updated.append(s)
    db.commit()
    return updated
