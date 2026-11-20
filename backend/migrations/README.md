Schema is defined by the SQLAlchemy models and created at startup via Base.metadata.create_all. For this local small application no destructive migration is run. Back up named db-data before modifying schemas.

v2 adds `sample_labels` (one origin/grade per tasting reading), `calibrations` (frozen targets plus sample snapshot and SHA256) and `calibration_activations` (one active calibration per study). `create_all` only creates missing tables; existing rows get no label until an analyst registers one, and the calibration form will reject a batch containing unlabeled samples.
