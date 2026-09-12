# [修复 2026-09-04] 标识分类和供应商模型
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class SignageCategory(Base):
    """标识分类"""
    __tablename__ = "signage_categories"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    code = Column(String(50), nullable=False, unique=True)
    description = Column(String(500))
    # [修复 2026-09-05] 新增 color 分类颜色（十六进制，如 #2F9E64），用于标记点位着色
    color = Column(String(20))
    # [修复 2026-09-05] 新增 shape 标记形状（circle/square/triangle/diamond/star），
    # 与颜色组合后渲染在标识平面图的标记点上，便于直观区分不同分类
    shape = Column(String(20), nullable=False, default="circle")
    # [新增 2026-09-05] 巡检周期（天）：按分类计算巡检到期/超期预警；留空表示该分类不参与巡检预警
    inspection_cycle_days = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Supplier(Base):
    """供应商"""
    __tablename__ = "suppliers"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    type = Column(String(50), nullable=False, default="manufacturer")  # manufacturer: 制作厂商
    contact_person = Column(String(100))
    phone = Column(String(50))
    address = Column(String(500))
    email = Column(String(200))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())