from src.services import studies,runs,calibrations,labels
# Controllers keep endpoint contracts separate from persistence and calculation.
def overview(db): return {'studies':studies.list_studies(db),'runs':runs.list_runs(db)}
def create_study(db,data,user): return studies.create(db,data,user)
def list_rows(db,id): return studies.observations(db,id)
def save_row(db,id,data,user,row_id=None): return studies.save_observation(db,id,data,user,row_id)
def create_run(db,data,user): return runs.create(db,data,user)
def review_run(db,id,data,user): return runs.approve(db,id,data,user)

def create_calibration(db,data,user): return calibrations.create(db,data,user)
def list_calibrations(db,study_id=None): return calibrations.list_calibrations(db,study_id)
def get_calibration(db,id): return calibrations.get(db,id)
def active_calibration(db,study_id): return calibrations.active(db,study_id)
def label_row(db,study_id,row_id,data,user): return labels.register(db,study_id,row_id,data,user)
