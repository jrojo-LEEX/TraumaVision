"""
models.py — Tablas de la base de datos.

Cada clase es una tabla y cada atributo una columna.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database.db import Base
from config.settings import ABNORMAL_THRESHOLD


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Médico que usa la app."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False, default="")  # ver app/security.py
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    picture_url = Column(String(500))
    created_at = Column(DateTime, default=_utcnow)
    last_login = Column(DateTime, default=_utcnow)

    analyses = relationship("Analysis", back_populates="user")
    studies = relationship("Study", back_populates="user")


class Study(Base):
    """Estudio de varias imágenes (un ZIP con DICOM)."""

    __tablename__ = "studies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    original_filename = Column(String(500))
    total_images = Column(Integer, default=0)
    images_with_findings = Column(Integer, default=0)
    anatomical_region = Column(String(50), nullable=True)
    model_version = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="studies")
    analyses = relationship("Analysis", back_populates="study")


class Analysis(Base):
    """El análisis de una imagen."""

    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    study_id = Column(Integer, ForeignKey("studies.id"), nullable=True, index=True)

    original_image_path = Column(String(500), nullable=False)
    annotated_image_path = Column(String(500))  # la imagen con las cajas dibujadas
    report_text = Column(Text)

    # El score más alto de YOLO después de NMS. NO es una probabilidad de fractura.
    max_detection_confidence = Column(Float, default=0.0)
    is_abnormal = Column(Boolean, default=False)
    inference_time_ms = Column(Float)

    anatomical_region = Column(String(50), nullable=True)
    model_version = Column(String(100), nullable=True)
    routing_method = Column(String(20), nullable=True)   # 'manual' | 'dicom' | 'auto'
    urgency = Column(String(10), nullable=True)          # 'HIGH' | 'MEDIUM' | 'LOW'
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="analyses")
    study = relationship("Study", back_populates="analyses")
    feedback = relationship("Feedback", back_populates="analysis", uselist=False)
    detection_boxes = relationship(
        "DetectionBox", back_populates="analysis", cascade="all, delete-orphan"
    )

    @property
    def findings_above_abnormal(self) -> int:
        """Cajas con confianza en o sobre el umbral de anormalidad."""
        return sum(1 for b in self.detection_boxes if b.confidence >= ABNORMAL_THRESHOLD)


class DetectionBox(Base):
    """Una caja (bounding box) de un análisis, en píxeles de la imagen original."""

    __tablename__ = "detection_boxes"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    x1 = Column(Integer, nullable=False)
    y1 = Column(Integer, nullable=False)
    x2 = Column(Integer, nullable=False)
    y2 = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    label = Column(String(50), default="fracture")

    analysis = relationship("Analysis", back_populates="detection_boxes")


class Feedback(Base):
    """Opinión del médico sobre un análisis (una por análisis)."""

    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), unique=True, nullable=False)
    agreed = Column(Boolean, nullable=False)
    observations = Column(Text)
    correct_diagnosis = Column(String(500))
    created_at = Column(DateTime, default=_utcnow)

    analysis = relationship("Analysis", back_populates="feedback")
