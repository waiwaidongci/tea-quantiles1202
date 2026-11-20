from fastapi import HTTPException
from sqlalchemy import select
from src.config.domain import DOMAIN
from src.models.calibration import SampleLabel
from src.models.observation import Observation

def validate(origin,grade):
    if origin not in DOMAIN['origins']: raise ValueError('产地必须为 '+', '.join(DOMAIN['origins']))
    if grade not in DOMAIN['grades']: raise ValueError('等级必须为 '+', '.join(DOMAIN['grades']))
    return origin,grade

def for_rows(db,study_id):
    rows=db.execute(select(SampleLabel).join(Observation,Observation.id==SampleLabel.observation_id)
                    .where(Observation.study_id==study_id)).scalars()
    return {label.observation_id:label for label in rows}

def register(db,study_id,row_id,data,user):
    row=db.get(Observation,row_id)
    if not row or row.study_id!=study_id: raise HTTPException(404,'记录不存在')
    try: origin,grade=validate(data.origin,data.grade)
    except ValueError as error: raise HTTPException(422,str(error))
    label=db.scalar(select(SampleLabel).where(SampleLabel.observation_id==row_id))
    if label:
        label.origin=origin;label.grade=grade
    else:
        db.add(SampleLabel(observation_id=row_id,origin=origin,grade=grade))
    from src.services.audits import log
    log(db,user,'sample.label',f'{study_id}/{row.source_key}: {origin}/{grade}')
    db.commit()
    return {'observation_id':row_id,'origin':origin,'grade':grade}
