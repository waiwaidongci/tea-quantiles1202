import os
from fastapi import HTTPException
from sqlalchemy import select
from redis import Redis
from src.config.domain import DOMAIN
from src.models.study import Study
from src.models.calibration import Calibration, CalibrationActivation, SampleLabel
from src.models.observation import Observation
from src.services import studies
from src.services.allocation import (AllocationInfeasible, allocate, verify_calibration,
                                     weighted_distribution, unweighted_distribution)
from src.services.audits import log
from src.utils.serializers import record, now, checksum


def _targets(values,allowed,label):
    if not isinstance(values,dict):
        raise ValueError(label+'目标必须是类别到份数的映射')
    unknown=[str(k) for k in values if k not in allowed]
    if unknown: raise ValueError(f"未知{label}：{', '.join(unknown)}")
    out={}
    for key,n in values.items():
        if isinstance(n,bool) or not isinstance(n,(int,float)) or int(n)!=n or n<0:
            raise ValueError(f'{label} {key} 的目标份数必须是非负整数')
        if n>5000: raise ValueError(label+'目标份数超出上限')
        out[key]=int(n)
    for key in allowed: out.setdefault(key,0)
    if sum(out.values())==0: raise ValueError(f'{label}目标份数合计必须大于 0')
    return out


def validate_targets(origin_targets,grade_targets):
    return (_targets(origin_targets,DOMAIN['origins'],'产地'),
            _targets(grade_targets,DOMAIN['grades'],'等级'))


def snapshot_rows(db,study_id):
    """Freeze observations together with their registered origin/grade labels."""
    rows=db.execute(select(Observation,SampleLabel)
                    .outerjoin(SampleLabel,SampleLabel.observation_id==Observation.id)
                    .where(Observation.study_id==study_id)
                    .order_by(Observation.id)).all()
    snapshot=[];missing=[]
    for observation,label in rows:
        if not label:
            missing.append(observation.source_key)
            continue
        snapshot.append({'source_key':observation.source_key,
                         'origin':label.origin,'grade':label.grade,
                         'values':observation.values})
    if missing:
        raise HTTPException(422,'以下茶样尚未登记产地和等级：'+'、'.join(missing[:8]))
    return snapshot


def create(db,data,user):
    studies.require(db,data.study_id)
    # Serialize against activation so a newer application cannot race an older
    # worker into becoming active after this request exists.
    db.execute(select(Study.id).where(Study.id==data.study_id).with_for_update()).first()
    try:
        origin_targets,grade_targets=validate_targets(data.origin_targets,data.grade_targets)
    except (ValueError,TypeError) as error:
        raise HTTPException(422,str(error))
    snapshot=snapshot_rows(db,data.study_id)
    if not snapshot: raise HTTPException(422,'先录入至少一条带产地和等级的茶样')
    payload=checksum({'origin_targets':origin_targets,'grade_targets':grade_targets,
                      'snapshot':snapshot})
    calibration=Calibration(study_id=data.study_id,name=data.name,status='queued',
                            origin_targets=origin_targets,grade_targets=grade_targets,
                            snapshot=snapshot,checksum=payload,created_at=now())
    db.add(calibration);db.flush()
    # Older pending applications can never take effect once a newer request
    # exists; completed archives keep their status but lose activation rights.
    for older in db.scalars(select(Calibration).where(
            Calibration.study_id==data.study_id,Calibration.id!=calibration.id,
            Calibration.status.in_(['queued','running']))):
        older.status='superseded'
    log(db,user,'calibration.queue',str(calibration.id));db.commit()
    _enqueue(calibration.id)
    return get(db,calibration.id)


def _enqueue(id):
    try:
        Redis.from_url(os.environ['REDIS_URL']).rpush('calibration-queue',id)
    except Exception:
        # The worker recovery loop re-queues pending rows on restart.
        pass


def get(db,id):
    calibration=db.get(Calibration,id)
    if not calibration: raise HTTPException(404,'校准申请不存在')
    result=record(calibration)
    activation=db.get(CalibrationActivation,calibration.study_id)
    result['active']=bool(activation and activation.calibration_id==id)
    result['active_calibration_id']=activation.calibration_id if activation else None
    return result


def list_calibrations(db,study_id=None):
    """Lightweight index; use get() for the frozen snapshot and result."""
    query=select(Calibration.id).order_by(Calibration.id.desc())
    if study_id: query=query.where(Calibration.study_id==study_id)
    rows=[]
    for id in db.scalars(query):
        row=get(db,id)
        row.pop('snapshot',None);row.pop('result',None)
        rows.append(row)
    return rows


def active(db,study_id):
    activation=db.get(CalibrationActivation,study_id)
    if not activation: return None
    calibration=db.get(Calibration,activation.calibration_id)
    if not calibration: return None
    row=record(calibration)
    row['activated_at']=activation.activated_at
    row['active']=True
    return row


def compute(origin_targets,grade_targets,snapshot):
    """Pure calculation executed by the worker; never touches the database."""
    samples=[{'source_key':row['source_key'],'values':row['values'],
              'origin':row['origin'],'grade':row['grade']} for row in snapshot]
    try:
        solved=allocate(samples,origin_targets,grade_targets)
    except AllocationInfeasible as error:
        return 'infeasible',{
            'diagnostics':error.diagnostics,
            'origin_targets':origin_targets,'grade_targets':grade_targets,
            'message':error.diagnostics['message'],
            'blocking':error.diagnostics.get('blocking',[]),
            'caveat':'两轴各自可达不等于可以同时达标；请调整目标份数或补充缺失格子的茶样。',
        }
    total=sum(origin_targets.values())
    weighted,_=weighted_distribution(samples,solved['allocation_map'],
                                     solved['actual_map'],total)
    result={
        'diagnostics':solved['diagnostics'],
        'origins':solved['origins'],'grades':solved['grades'],
        'origin_targets':origin_targets,'grade_targets':grade_targets,
        'received':solved['actual'],'allocated':solved['allocation'],
        'cells':solved['cells'],'objective':solved['objective'],'total':total,
        'weighted':weighted,'raw':unweighted_distribution(samples),
        'caveat':'加权分布把每个格子的整数份数平均分给该格全部茶样；仅用于本次校准，不改变原始观测。',
    }
    verify_calibration(result)
    return 'completed',result


def process(db,id):
    """Worker entry point; the study row lock is held through activation."""
    calibration=db.get(Calibration,id)
    if not calibration: return
    study_id=calibration.study_id
    db.execute(select(Study.id).where(Study.id==study_id).with_for_update()).first()
    db.refresh(calibration)
    if calibration.status in ('superseded','completed','infeasible','failed'): return
    try:
        if checksum({'origin_targets':calibration.origin_targets,
                     'grade_targets':calibration.grade_targets,
                     'snapshot':calibration.snapshot})!=calibration.checksum:
            raise ValueError('输入快照校验失败')
        status,result=compute(calibration.origin_targets,calibration.grade_targets,
                              calibration.snapshot)
        calibration.result=result;calibration.status=status
        _maybe_activate(db,calibration)
        db.commit()
    except Exception as error:
        db.rollback()
        calibration=db.get(Calibration,id)
        if calibration and calibration.status!='superseded':
            calibration.status='failed';calibration.error=str(error);db.commit()


def _newer_exists(db,calibration):
    return db.scalar(select(Calibration.id).where(
        Calibration.study_id==calibration.study_id,
        Calibration.id>calibration.id).limit(1))


def _maybe_activate(db,calibration):
    """Verify, then switch only if this is still the newest application."""
    if calibration.status=='completed':
        try: verify_calibration(calibration.result)
        except ValueError as error:
            calibration.status='failed'
            calibration.error='激活前核对失败：'+str(error)
            return
    newer=_newer_exists(db,calibration)
    if newer:
        calibration.status='superseded'
        calibration.result=dict(calibration.result or {},superseded_by=newer)
        return
    activation=db.get(CalibrationActivation,calibration.study_id)
    if activation and activation.calibration_id>calibration.id:
        # An older request finished late; keep the newer active version.
        calibration.status='superseded'
        calibration.result=dict(calibration.result or {},
                                superseded_by=activation.calibration_id)
        return
    if calibration.status!='completed':
        # Infeasible or failed: the previously active version stays in force.
        calibration.result=dict(calibration.result or {},
                                retained_active_id=activation.calibration_id if activation else None)
        return
    if activation:
        activation.calibration_id=calibration.id
        activation.activated_at=now();activation.checksum=calibration.checksum
    else:
        db.add(CalibrationActivation(study_id=calibration.study_id,
                                     calibration_id=calibration.id,
                                     activated_at=now(),checksum=calibration.checksum))


def recover(db):
    return list(db.scalars(select(Calibration.id).where(
        Calibration.status.in_(['queued','running'])).order_by(Calibration.id)))
