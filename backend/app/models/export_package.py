# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base
from app.utils import utc_now


class ExportPackage(Base):
    __tablename__ = "export_packages"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, nullable=True)
    department_name = Column(String(100), default="全部科室")
    # [修复 2026-08-28] 记录本次打包的照片类型筛选（front/side/card，逗号分隔），便于列表展示
    photo_types = Column(String(50), nullable=True)
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, default=0)
    status = Column(String(20), default="packing")  # packing / completed / expired
    created_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
