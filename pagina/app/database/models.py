"""
models.py — Modelos de las tablas de la base de datos.

Cada clase es una tabla y cada atributo una columna. Es el diseño de las fichas
donde la app guarda usuarios, análisis, hallazgos y feedback.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Médico que usa la app."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    # PBKDF2-HMAC-SHA256 con salt por usuario. Formato: "pbkdf2_sha256$iter$salt$hash"
    password_hash = Column(String(255), nullable=False, default="")
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    picture_url = Column(String(500))
    created_at = Column(DateTime, default=_utcnow)
    last_login = Column(DateTime, default=_utcnow)

    analyses = relationship("Analysis", back_populates="user")
    studies = relationship("Study", back_populates="user")


class Study(Base):
    """Estudio multi-imagen (ZIP con varios cortes DICOM)."""

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
    """Un análisis realizado sobre una imagen."""

    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    study_id = Column(Integer, ForeignKey("studies.id"), nullable=True, index=True)

    original_image_path = Column(String(500), nullable=False)
    # Antes se llamaba heatmap_image_path, herencia de la etapa Grad-CAM. Lo que
    # guarda es la imagen con los bounding boxes dibujados, no un mapa de calor.
    annotated_image_path = Column(String(500))
    report_text = Column(Text)

    # Antes se llamaba fracture_probability. Es el máximo de las confianzas
    # post-NMS de YOLO: NO es una probabilidad de fractura.
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
        """Cajas que superan el umbral de anormalidad.

        Distinto de len(detection_boxes), que incluye los hallazgos de baja
        confianza que se dibujan sólo como referencia.
        """
        from config.settings import ABNORMAL_THRESHOLD

        return sum(1 for b in self.detection_boxes if b.confidence >= ABNORMAL_THRESHOLD)


class DetectionBox(Base):
    """Bounding box individual de un análisis."""

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
    """Opinión del médico sobre un análisis."""

    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), unique=True, nullable=False)
    agreed = Column(Boolean, nullable=False)
    observations = Column(Text)
    correct_diagnosis = Column(String(500))
    created_at = Column(DateTime, default=_utcnow)

    analysis = relationship("Analysis", back_populates="feedback")


# Registro explícito de todas las tablas, para que create_all() nunca dependa
# del efecto colateral de importar el módulo.
ALL_MODELS = (User, Study, Analysis, DetectionBox, Feedback)
