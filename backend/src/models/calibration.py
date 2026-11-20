from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey
from src.config.database import Base


class SampleLabel(Base):
    """Origin and grade registered for one tasting reading (one tea sample)."""
    __tablename__='sample_labels'
    id=Column(Integer,primary_key=True)
    observation_id=Column(Integer,ForeignKey('observations.id'),unique=True,nullable=False)
    origin=Column(String(40),nullable=False)
    grade=Column(String(40),nullable=False)


class Calibration(Base):
    __tablename__='calibrations'
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    name=Column(String(120),nullable=False)
    status=Column(String(20),default='queued')
    origin_targets=Column(JSON,nullable=False)
    grade_targets=Column(JSON,nullable=False)
    snapshot=Column(JSON,nullable=False)
    checksum=Column(String(64),nullable=False)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    created_at=Column(String(40),nullable=False)


class CalibrationActivation(Base):
    """Single row per study: which calibration is currently in force."""
    __tablename__='calibration_activations'
    study_id=Column(Integer,ForeignKey('studies.id'),primary_key=True)
    calibration_id=Column(Integer,ForeignKey('calibrations.id'),nullable=False)
    activated_at=Column(String(40),nullable=False)
    checksum=Column(String(64),nullable=False)


SampleLabelModel=SampleLabel
CalibrationModel=Calibration
ActivationModel=CalibrationActivation
