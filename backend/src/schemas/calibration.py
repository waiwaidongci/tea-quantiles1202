from pydantic import BaseModel,Field

class CalibrationInput(BaseModel):
    study_id:int=Field(gt=0)
    name:str=Field(min_length=2,max_length=120)
    origin_targets:dict=Field(default_factory=dict)
    grade_targets:dict=Field(default_factory=dict)

class SampleLabelInput(BaseModel):
    origin:str=Field(min_length=1,max_length=40)
    grade:str=Field(min_length=1,max_length=40)
