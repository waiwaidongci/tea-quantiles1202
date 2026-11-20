"""Tests for the calibration engine. Run with:

    cd backend && JWT_SECRET=test DATABASE_URL=sqlite:////tmp/t.db \
        REDIS_URL=redis://127.0.0.1:1/0 python -m unittest discover -s tests -v
"""
import itertools
import random
import unittest

from src.services.allocation import (AllocationInfeasible, allocate, diagnose,
                                     unweighted_distribution, verify_calibration,
                                     weighted_distribution)


def samples(cells):
    rows = []
    for (origin, grade), count in cells.items():
        for i in range(count):
            rows.append({'source_key': f'{origin}-{grade}-{i}', 'origin': origin,
                         'grade': grade,
                         'values': {'moisture': 5.0 + i * 0.1, 'extract': 30.0}})
    return rows


def brute_force(cells, origin_targets, grade_targets):
    origins = sorted({o for o, _ in cells} | set(origin_targets))
    grades = sorted({g for _, g in cells} | set(grade_targets))
    support = [(o, g) for o in origins for g in grades if cells.get((o, g), 0) > 0]
    total = sum(origin_targets.values())
    best = None

    def walk(index, remaining, assigned):
        nonlocal best
        if index == len(support):
            if remaining:
                return
            allocation = dict(zip(support, assigned))
            if any(sum(allocation.get((o, g), 0) for g in grades) != origin_targets.get(o, 0)
                   for o in origins):
                return
            if any(sum(allocation.get((o, g), 0) for o in origins) != grade_targets.get(g, 0)
                   for g in grades):
                return
            objective = sum(abs(allocation[cell] - cells.get(cell, 0)) for cell in support)
            vector = tuple(allocation.get((o, g), 0) for o in origins for g in grades)
            if best is None or (objective, vector) < best:
                best = (objective, vector)
            return
        for value in range(remaining + 1):
            walk(index + 1, remaining - value, assigned + [value])

    walk(0, total, [])
    return best


class AllocationTest(unittest.TestCase):
    def test_exact_fit_is_zero_cost(self):
        cells = {('东岭', '特级'): 5, ('东岭', '一级'): 1,
                 ('南坡', '特级'): 1, ('南坡', '一级'): 5}
        solved = allocate(samples(cells), {'东岭': 6, '南坡': 6}, {'特级': 6, '一级': 6})
        self.assertEqual(solved['objective'], 0)
        # Grades sort as 一级 (U+4E00) before 特级 (U+7279).
        self.assertEqual(solved['grades'], ['一级', '特级'])
        self.assertEqual(solved['allocation'], [[1, 5], [5, 1]])

    def test_random_against_brute_force(self):
        rng = random.Random(11)
        origins, grades = ['A', 'B', 'C'], ['X', 'Y', 'Z']
        checked = 0
        for _ in range(120):
            cells = {(o, g): rng.randint(0, 2) for o in origins for g in grades}
            if not sum(cells.values()):
                continue
            total = rng.randint(1, 6)
            origin_targets = {o: 0 for o in origins}
            grade_targets = {g: 0 for g in grades}
            for _ in range(total):
                origin_targets[rng.choice(origins)] += 1
                grade_targets[rng.choice(grades)] += 1
            if any(origin_targets[o] and not sum(cells[(o, g)] for g in grades)
                   for o in origins):
                continue
            if any(grade_targets[g] and not sum(cells[(o, g)] for o in origins)
                   for g in grades):
                continue
            expected = brute_force(cells, origin_targets, grade_targets)
            try:
                solved = allocate(samples(cells), origin_targets, grade_targets)
            except AllocationInfeasible:
                self.assertIsNone(expected)
                continue
            vector = tuple(solved['allocation_map'][(o, g)]
                           for o in solved['origins'] for g in solved['grades'])
            self.assertEqual((solved['objective'], vector), expected)
            checked += 1
        self.assertGreater(checked, 60)

    def test_lexicographic_tie_break(self):
        # Two optimal vectors with the same L1 cost; the lexicographically
        # smaller one (reading origin-major, then grade) must win.
        cells = {('A', 'X'): 1, ('A', 'Y'): 1, ('B', 'X'): 1, ('B', 'Y'): 1}
        solved = allocate(samples(cells), {'A': 2, 'B': 1}, {'X': 1, 'Y': 2})
        self.assertEqual(solved['allocation'], [[1, 1], [0, 1]])
        self.assertEqual(solved['objective'], 1)

    def test_empty_cells_are_zero(self):
        cells = {('A', 'X'): 2, ('B', 'Y'): 2}
        solved = allocate(samples(cells), {'A': 2, 'B': 2}, {'X': 2, 'Y': 2})
        self.assertEqual(solved['allocation'], [[2, 0], [0, 2]])


class InfeasibilityTest(unittest.TestCase):
    def blocked(self, cells, origin_targets, grade_targets):
        with self.assertRaises(AllocationInfeasible) as context:
            allocate(samples(cells), origin_targets, grade_targets)
        return context.exception.diagnostics

    def test_missing_origin_class(self):
        cells = {('A', 'X'): 2, ('A', 'Y'): 2}
        diagnostics = self.blocked(cells, {'A': 2, 'B': 2}, {'X': 2, 'Y': 2})
        self.assertEqual(diagnostics['code'], 'target_without_samples')
        self.assertFalse(diagnostics['axis']['origin']['reachable'])
        self.assertEqual(diagnostics['axis']['origin']['missing'], ['B'])

    def test_missing_grade_class(self):
        cells = {('A', 'X'): 2, ('B', 'X'): 2}
        diagnostics = self.blocked(cells, {'A': 2, 'B': 2}, {'X': 2, 'Y': 2})
        self.assertEqual(diagnostics['code'], 'target_without_samples')
        self.assertFalse(diagnostics['axis']['grade']['reachable'])

    def test_totals_mismatch(self):
        cells = {('A', 'X'): 2, ('B', 'X'): 2}
        diagnostics = self.blocked(cells, {'A': 2, 'B': 3}, {'X': 4, 'Y': 0})
        self.assertEqual(diagnostics['code'], 'totals_mismatch')

    def test_each_axis_reachable_but_not_together(self):
        # A only has X samples, B only has Y samples.  Both axes can be hit
        # independently, but no joint integer allocation exists.
        cells = {('A', 'X'): 5, ('B', 'Y'): 5}
        diagnostics = self.blocked(cells, {'A': 5, 'B': 5}, {'X': 3, 'Y': 7})
        self.assertEqual(diagnostics['code'], 'support_disconnected')
        self.assertTrue(diagnostics['individually_reachable'])
        self.assertFalse(diagnostics['simultaneous_feasible'])
        unbalanced = [c for c in diagnostics['components'] if not c['balanced']]
        self.assertEqual(len(unbalanced), 2)

    def test_diagnose_does_not_raise(self):
        cells = {('A', 'X'): 1}
        diagnostics = diagnose(samples(cells), {'A': 1}, {'X': 1})
        self.assertTrue(diagnostics['feasible'])


class WeightedDistributionTest(unittest.TestCase):
    def test_split_weights_and_cumulative_sum(self):
        cells = {('A', 'X'): 2, ('B', 'Y'): 2}
        rows = samples(cells)
        solved = allocate(rows, {'A': 1, 'B': 2}, {'X': 1, 'Y': 2})
        distribution, weighted = weighted_distribution(
            rows, solved['allocation_map'], solved['actual_map'], 3)
        self.assertAlmostEqual(distribution['weight_sum'], 3.0)
        self.assertAlmostEqual(distribution['cdf_final'], 1.0)
        self.assertEqual(len(weighted), len(rows))
        # A/X cell has 1 allocated over 2 samples -> weight 1/2 each.
        self.assertAlmostEqual(weighted[0][1], 0.5)
        verify_calibration({
            'total': 3, 'origins': solved['origins'], 'grades': solved['grades'],
            'origin_targets': {'A': 1, 'B': 2}, 'grade_targets': {'X': 1, 'Y': 2},
            'allocated': solved['allocation'], 'weighted': distribution,
            'cells': solved['cells'],
        })

    def test_verification_rejects_bad_weights(self):
        with self.assertRaises(ValueError):
            verify_calibration({
                'total': 2, 'origins': ['A'], 'grades': ['X'],
                'origin_targets': {'A': 2}, 'grade_targets': {'X': 2},
                'allocated': [[2]],
                'weighted': {'weight_sum': 1.0, 'points': [[1.0, 1.0]]},
                'cells': [],
            })

    def test_unweighted_matches_linear_interpolation(self):
        rows = samples({('A', 'X'): 4})
        distribution = unweighted_distribution(rows)
        self.assertAlmostEqual(distribution['quantiles']['中位数'], 5.15)


if __name__ == '__main__':
    unittest.main()
