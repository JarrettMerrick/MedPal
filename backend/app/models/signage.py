# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Signage(Base):
    __tablename__ = "signages"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False)
    # [修复 2026-09-04] 新增类别类型字段：标识标牌/平面宣传
    category_type = Column(String(20), nullable=False, default="标识标牌")
    material = Column(String(100))
    size_spec = Column(String(100))
    install_date = Column(Date)
    warranty_expire = Column(Date)
    # [新增 2026-09-05] 标识有效期：long_term 长期标识（不设到期时间）/ temporary 临时标识（必填到期日）
    validity_type = Column(String(20), nullable=False, default="long_term")
    validity_until = Column(Date)
    campus = Column(String(100))
    building = Column(String(100))
    floor = Column(String(20))
    # [新增 2026-09-12] 具体区域：当 zone_type 为「楼层导视/宣传」时可选填，支持多选，
    # 存区域名称、多个以「,」分隔（与「院区管理」areas 表按名称对应）。
    # 选填：为空表示未指定区域，不影响任何既有校验；模型新增列由启动自动补列覆盖。
    area = Column(String(500))
    # [修复 2026-09-04] 新增所属区域类型字段：院区导视/宣传、楼栋导视/宣传、楼层导视/宣传
    zone_type = Column(String(30), nullable=False, default="院区导视/宣传")
    location_desc = Column(String(500))
    display_text_cn = Column(String(500))
    display_text_en = Column(String(500))
    department_id = Column(Integer, ForeignKey("departments.id"))
    status = Column(String(20), default="normal")
    oa_number = Column(String(100))
    manufacturer = Column(String(200))
    vendor_contact = Column(String(200))
    design_photo = Column(String(500))
    # [新增 2026-09-17] 关联「文件管理」中的设计文件记录（引用共享）：
    # 多条标识可复用同一份标准设计文件（磁盘只存一份）；
    # design_photo 保留为路径快照，导出 / 详情等既有链路零改动，
    # 本列用于文件库的引用统计与删除保护。
    design_file_id = Column(Integer, ForeignKey("design_files.id"), nullable=True, index=True)
    installation_photo = Column(String(500))
    created_by = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())
    updated_by = Column(String(20))
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    department = relationship("Department", foreign_keys=[department_id])
    points = relationship("SignagePoint", back_populates="signage")
    photos = relationship("SignagePhoto", back_populates="signage")
    history = relationship("SignageHistory", back_populates="signage")
    inspections = relationship("SignageInspection", back_populates="signage")


class FloorPlan(Base):
    __tablename__ = "floor_plans"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    # [修复 2026-09-05] 移除原 type 字段，新增 category 平面类别（院区平面/楼层平面）
    category = Column(String(20), nullable=False, default="楼层平面")
    campus = Column(String(100))
    building = Column(String(100))
    floor = Column(String(20))
    image_url = Column(String(500))
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    # [修复 2026-09-05] 新增 floor_code 关联楼层编号（如 F3/-1）与 description 描述
    floor_code = Column(String(20))
    description = Column(Text)
    # [修复 2026-09-05] 新增 floor_id 外键：将平面图楼层与「院区管理」中的楼层（floors 表）关联，
    # 楼层不再由用户自由填写，而是取自院区→楼栋→楼层三级数据，保证楼层口径全院一致。
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)
    points = relationship("SignagePoint", back_populates="floor_plan")


class SignagePoint(Base):
    __tablename__ = "signage_points"
    id = Column(Integer, primary_key=True)
    signage_id = Column(Integer, ForeignKey("signages.id"))
    floor_plan_id = Column(Integer, ForeignKey("floor_plans.id"))
    x_percent = Column(Float)
    y_percent = Column(Float)
    pin_icon = Column(String(50))
    pin_color = Column(String(20))
    signage = relationship("Signage", back_populates="points")
    floor_plan = relationship("FloorPlan", back_populates="points")


class SignagePhoto(Base):
    __tablename__ = "signage_photos"
    id = Column(Integer, primary_key=True)
    signage_id = Column(Integer, ForeignKey("signages.id"))
    photo_type = Column(String(20))
    photo_url = Column(String(500))
    caption = Column(String(200))
    uploaded_by = Column(String(20))
    uploaded_at = Column(DateTime, server_default=func.now())
    signage = relationship("Signage", back_populates="photos")


class SignageHistory(Base):
    __tablename__ = "signage_history"
    id = Column(Integer, primary_key=True)
    signage_id = Column(Integer, ForeignKey("signages.id"))
    field_name = Column(String(50))
    old_value = Column(Text)
    new_value = Column(Text)
    oa_number = Column(String(100))
    changed_by = Column(String(20))
    changed_at = Column(DateTime, server_default=func.now())
    # [修复 2026-09-04] 新增 snapshot 字段，存储变更时的完整标识快照（JSON 字符串）
    snapshot = Column(Text)
    signage = relationship("Signage", back_populates="history")


class SignageInspection(Base):
    __tablename__ = "signage_inspections"
    id = Column(Integer, primary_key=True)
    signage_id = Column(Integer, ForeignKey("signages.id"))
    inspection_date = Column(Date)
    inspector = Column(String(20))
    result = Column(String(20))
    notes = Column(Text)
    # [新增 2026-09-07] 巡检现场照片（客户端压缩后上传，可选）
    photo = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    signage = relationship("Signage", back_populates="inspections")


class SignageRepair(Base):
    """[新增 2026-09-08] 标识维修记录：预警（状态异常）发起维修 → 维修处理中 → 完成维修

    - repair_party: vendor=供应商维修（必选供应商，OA单号可选）/ engineering=工程部维修（可直接确认）
    - 发起维修后标识 status 置为 repair_in_progress；完成后置回 normal
    - repair_photo: 维修完成照片（可选）；上传后同步替换标识的安装现场照片 installation_photo
    - repair_photo_before: [新增 2026-09-09] 维修前照片，发起维修时自动取自该标识最近一次巡检上传的现场照片
    - [修复 2026-09-09] 维修流程不写入历史版本（SignageHistory）：维修记录与"版本更新"历史严格区分，
      维修前后照片对比通过详情页「维修记录」查询展示
    """
    __tablename__ = "signage_repairs"
    id = Column(Integer, primary_key=True)
    signage_id = Column(Integer, ForeignKey("signages.id"))
    repair_party = Column(String(20), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    supplier_name = Column(String(200))
    oa_number = Column(String(100))
    repair_photo = Column(String(500))
    # [新增 2026-09-09] 维修前照片：发起维修时自动取自最近一次巡检上传的现场照片（无需另外上传）
    repair_photo_before = Column(String(500))
    started_by = Column(String(20))
    started_at = Column(DateTime, server_default=func.now())
    completed_by = Column(String(20))
    completed_at = Column(DateTime)
    # [新增 2026-09-09] 关联标识：维修记录列表/导出需带出标识编码、名称与位置信息
    signage = relationship("Signage", foreign_keys=[signage_id])