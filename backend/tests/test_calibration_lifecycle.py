"""Lifecycle tests: newest-wins activation, no overwrite by an older request,
infeasible requests keep the previous version in force, verify-before-switch.
"""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models import calibration
from src.models.study import Study
from src.models.user import User
from src.models.observation import Observation
from src.services import calibrations


class LifecycleBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session() as db:
            user = User(email='a@demo.local', role='admin', password_hash='x')
            db.add(user)
            db.flush()
            study = Study(name='t', source_filename='x')
            db.add(study)
            db.flush()
            for i, (origin, grade) in enumerate(
                    [('东岭', '特级')] * 5 + [('东岭', '一级')] * 1
                    + [('南坡', '特级')] * 1 + [('南坡', '一级')] * 5):
                row = Observation(study_id=study.id, source_key=f'S{i}',
                                  values={'moisture': 5.0 + i * 0.1, 'extract': 30.0})
                db.add(row)
                db.flush()
                db.add(calibration.SampleLabel(observation_id=row.id,
                                               origin=origin, grade=grade))
            db.commit()
            self.study_id = study.id
            self.user_id = user.id

    def apply(self, name, origin_targets, grade_targets):
        class Data:
            pass
        data = Data()
        data.study_id = self.study_id
        data.name = name
        data.origin_targets = origin_targets
        data.grade_targets = grade_targets
        with self.Session() as db:
            return calibrations.create(db, data, db.get(User, self.user_id))['id']

    def process(self, id):
        with self.Session() as db:
            calibrations.process(db, id)

    def status(self, id):
        with self.Session() as db:
            return db.get(calibration.Calibration, id).status

    def active(self):
        with self.Session() as db:
            row = calibrations.active(db, self.study_id)
            return row['id'] if row else None


class ActivationTest(LifecycleBase):
    def test_completed_newest_activates(self):
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        self.process(first)
        self.assertEqual(self.status(first), 'completed')
        self.assertEqual(self.active(), first)

    def test_newer_supersedes_pending_older(self):
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        second = self.apply('二', {'东岭': 8, '南坡': 4}, {'特级': 4, '一级': 8})
        self.assertEqual(self.status(first), 'superseded')
        self.process(first)          # older finishes late
        self.process(second)
        self.assertEqual(self.status(first), 'superseded')
        self.assertEqual(self.active(), second)

    def test_newer_wins_even_if_processed_first(self):
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        second = self.apply('二', {'东岭': 8, '南坡': 4}, {'特级': 4, '一级': 8})
        self.process(second)
        self.assertEqual(self.active(), second)
        self.process(first)
        self.assertEqual(self.status(first), 'superseded')
        self.assertEqual(self.active(), second)

    def test_slow_older_cannot_overwrite_active_newer(self):
        # Simulate the older request being computed out of order (queued before
        # the newer one but finishing after it).  Row-lock ordering in Postgres
        # plus the id check means activation is idempotently newest-wins.
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        second = self.apply('二', {'东岭': 8, '南坡': 4}, {'特级': 4, '一级': 8})
        self.process(second)
        # Force the old row back to queued to model a worker that started
        # before the newer application landed.
        with self.Session() as db:
            row = db.get(calibration.Calibration, first)
            row.status = 'queued'
            db.commit()
        self.process(first)
        self.assertEqual(self.status(first), 'superseded')
        self.assertEqual(self.active(), second)

    def test_infeasible_keeps_previous_active(self):
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        self.process(first)
        second = self.apply('二', {'东岭': 1}, {'二级': 1})
        self.process(second)
        self.assertEqual(self.status(second), 'infeasible')
        self.assertEqual(self.active(), first)
        with self.Session() as db:
            self.assertEqual(db.get(calibration.Calibration, second)
                             .result['diagnostics']['code'], 'target_without_samples')

    def test_verification_failure_blocks_switch(self):
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        self.process(first)
        second = self.apply('二', {'东岭': 8, '南坡': 4}, {'特级': 4, '一级': 8})
        # Corrupt the frozen result right before activation would happen by
        # making verify reject a well-formed snapshot: monkeypatch compute.
        original = calibrations.compute
        def broken(origin_targets, grade_targets, snapshot):
            status, result = original(origin_targets, grade_targets, snapshot)
            result['weighted']['weight_sum'] = 0.0
            return status, result
        calibrations.compute = broken
        try:
            self.process(second)
        finally:
            calibrations.compute = original
        self.assertEqual(self.status(second), 'failed')
        self.assertEqual(self.active(), first)
        with self.Session() as db:
            self.assertIn('激活前核对失败', db.get(calibration.Calibration, second).error)

    def test_reapplying_after_newer_reactivates(self):
        first = self.apply('一', {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        second = self.apply('二', {'东岭': 8, '南坡': 4}, {'特级': 4, '一级': 8})
        self.process(first)
        self.process(second)
        self.assertEqual(self.active(), second)
        third = self.apply('三', {'东岭': 7, '南坡': 5}, {'特级': 5, '一级': 7})
        self.process(third)
        self.assertEqual(self.active(), third)


if __name__ == '__main__':
    unittest.main()
