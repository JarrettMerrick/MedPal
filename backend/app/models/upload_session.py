# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import json
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database import Base
from app.utils import utc_now


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(String(36), unique=True, nullable=False, index=True)
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(String(50), nullable=False)
    photo_type = Column(String(20), nullable=False)  # front / side / card
    original_filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    chunk_size = Column(Integer, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    received_chunks = Column(Text, default="[]")
    status = Column(String(20), default="active")  # active / completed / expired
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def get_received(self):
        return json.loads(self.received_chunks) if self.received_chunks else []

    def add_received(self, chunk_index: int):
        chunks = self.get_received()
        if chunk_index not in chunks:
            chunks.append(chunk_index)
        self.received_chunks = json.dumps(chunks)
