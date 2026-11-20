"""Integer allocation core for origin × grade sample calibration.

The problem is a transportation problem over the cells that actually contain
samples.  Rows are origins, columns are grades, row/column sums are the two
frozen target sets and the cost of a cell is ``|allocated - received|``.
Cells without samples are fixed to zero.

Every cost is an integer, so the transportation polytope has an integral
optimum.  To obtain the required tie-break (smallest allocation vector in
lexicographic order after sorting by origin and then by grade) the ordinary
L1 objective is combined with a base-(F+1) lexicographic weight, where F is
the total target count.  The combined cost is an exact Python integer:

    combined = Q * L1 + sum_i(x_i * (F+1) ** (N-1-i))

with ``Q = (F+1) ** N``.  Since every x_i is between 0 and F, the second
term is a base-(F+1) representation of the allocation vector and numeric
order coincides with lexicographic order.  Q dominates every possible
secondary difference, so the L1 objective always wins first.
"""

from collections import deque
from fractions import Fraction


class AllocationInfeasible(Exception):
    def __init__(self, diagnostics):
        super().__init__(diagnostics.get('message', '无解'))
        self.diagnostics = diagnostics


def _matrix(origins, grades, values):
    return [[values.get((o, g), 0) for g in grades] for o in origins]


def _components(origins, grades, cells):
    """Connected components of the origin/grade support graph."""
    adjacency = {('o', o): [] for o in origins}
    adjacency.update({('g', g): [] for g in grades})
    for o, g in cells:
        adjacency[('o', o)].append(('g', g))
        adjacency[('g', g)].append(('o', o))
    seen = set()
    result = []
    for node in list(adjacency):
        if node in seen:
            continue
        stack = [node]
        seen.add(node)
        comp = {'origins': [], 'grades': []}
        while stack:
            kind, label = stack.pop()
            comp['origins' if kind == 'o' else 'grades'].append(label)
            for other in adjacency[(kind, label)]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        comp['origins'].sort()
        comp['grades'].sort()
        result.append(comp)
    return result


def diagnose(samples, origin_targets, grade_targets):
    """Return feasibility diagnostics without allocating anything."""
    actual = {}
    origin_counts = {}
    grade_counts = {}
    for sample in samples:
        o, g = sample['origin'], sample['grade']
        actual[(o, g)] = actual.get((o, g), 0) + 1
        origin_counts[o] = origin_counts.get(o, 0) + 1
        grade_counts[g] = grade_counts.get(g, 0) + 1

    origins = sorted(set(origin_counts) | set(origin_targets))
    grades = sorted(set(grade_counts) | set(grade_targets))
    origin_total = sum(origin_targets.values())
    grade_total = sum(grade_targets.values())

    origin_missing = sorted({o for o, n in origin_targets.items()
                             if n > 0 and origin_counts.get(o, 0) == 0})
    grade_missing = sorted({g for g, n in grade_targets.items()
                            if n > 0 and grade_counts.get(g, 0) == 0})
    origin_reachable = not origin_missing
    grade_reachable = not grade_missing
    individually_reachable = origin_reachable and grade_reachable

    cells = [cell for cell, n in actual.items() if n > 0]
    components = []
    for comp in _components(origins, grades, cells):
        ot = sum(origin_targets.get(o, 0) for o in comp['origins'])
        gt = sum(grade_targets.get(g, 0) for g in comp['grades'])
        comp.update({'origin_total': ot, 'grade_total': gt,
                     'balanced': ot == gt})
        components.append(comp)
    unbalanced = [c for c in components if not c['balanced']]

    diagnostics = {
        'feasible': False,
        'origin_total': origin_total,
        'grade_total': grade_total,
        'totals_match': origin_total == grade_total,
        'axis': {
            'origin': {'reachable': origin_reachable, 'missing': origin_missing},
            'grade': {'reachable': grade_reachable, 'missing': grade_missing},
        },
        'individually_reachable': individually_reachable,
        'simultaneous_feasible': False,
        'components': components,
    }

    if origin_total == 0 and grade_total == 0:
        diagnostics.update({
            'code': 'empty_target',
            'blocked_axis': 'both',
            'message': '两套目标总份数均为 0，无法形成校准后的含水率分布。',
            'blocking': ['产地目标合计 0', '等级目标合计 0'],
        })
        return diagnostics

    if origin_total != grade_total:
        diagnostics.update({
            'code': 'totals_mismatch',
            'blocked_axis': 'both',
            'message': (f'两套目标总份数不一致：产地合计 {origin_total}，'
                        f'等级合计 {grade_total}，两轴无法同时达标。'),
            'blocking': [f'产地目标合计 {origin_total}',
                         f'等级目标合计 {grade_total}'],
        })
        return diagnostics

    if origin_missing or grade_missing:
        blocking = [f'产地 {o} 目标 {origin_targets[o]} 份但没有登记茶样'
                    for o in origin_missing]
        blocking += [f'等级 {g} 目标 {grade_targets[g]} 份但没有登记茶样'
                     for g in grade_missing]
        diagnostics.update({
            'code': 'target_without_samples',
            'blocked_axis': ('both' if origin_missing and grade_missing
                             else 'origin' if origin_missing else 'grade'),
            'message': '目标中有类别没有可用茶样：' + '；'.join(blocking) + '。',
            'blocking': blocking,
        })
        return diagnostics

    if unbalanced:
        blocking = []
        for c in unbalanced:
            blocking.append(
                f"产地组 [{', '.join(c['origins'])}] 目标合计 {c['origin_total']}"
                f" ≠ 等级组 [{', '.join(c['grades'])}] 目标合计 {c['grade_total']}")
        diagnostics.update({
            'code': 'support_disconnected',
            'blocked_axis': 'both',
            'message': ('两轴各自可达，但产地与等级的样本支撑分组内目标不平衡，'
                        '因此无法同时达标：' + '；'.join(blocking) + '。'),
            'blocking': blocking,
        })
        return diagnostics

    diagnostics.update({
        'feasible': True,
        'simultaneous_feasible': True,
        'code': 'feasible',
        'blocked_axis': None,
        'message': '两套目标均可同时达标。',
        'blocking': [],
    })
    return diagnostics


class _MinCostFlow:
    """Successive shortest paths with SPFA; costs are arbitrary-precision ints."""

    def __init__(self, size):
        self.graph = [[] for _ in range(size)]

    def add(self, u, v, capacity, cost):
        self.graph[u].append([v, capacity, cost, len(self.graph[v])])
        self.graph[v].append([u, 0, -cost, len(self.graph[u]) - 1])

    def send(self, source, sink, need):
        size = len(self.graph)
        flow = 0
        cost = 0
        while flow < need:
            distance = [None] * size
            parent = [None] * size
            queued = [False] * size
            distance[source] = 0
            queue = deque([source])
            queued[source] = True
            while queue:
                u = queue.popleft()
                queued[u] = False
                for index, edge in enumerate(self.graph[u]):
                    v, capacity, edge_cost, _ = edge
                    if capacity <= 0:
                        continue
                    candidate = distance[u] + edge_cost
                    if distance[v] is None or candidate < distance[v]:
                        distance[v] = candidate
                        parent[v] = (u, index)
                        if not queued[v]:
                            queue.append(v)
                            queued[v] = True
            if distance[sink] is None:
                break
            pushed = need - flow
            v = sink
            while v != source:
                u, index = parent[v]
                pushed = min(pushed, self.graph[u][index][1])
                v = u
            v = sink
            while v != source:
                u, index = parent[v]
                edge = self.graph[u][index]
                edge[1] -= pushed
                self.graph[v][edge[3]][1] += pushed
                v = u
            flow += pushed
            cost += pushed * distance[sink]
        return flow, cost


def _solve(origins, grades, actual, origin_targets, grade_targets):
    cells = [(o, g) for o in origins for g in grades if actual.get((o, g), 0) > 0]
    total = sum(origin_targets.values())
    if total == 0:
        return {(o, g): 0 for o in origins for g in grades}

    index = {cell: i for i, cell in enumerate(cells)}
    source = 0
    origin_node = {o: 1 + i for i, o in enumerate(origins)}
    grade_node = {g: 1 + len(origins) + i for i, g in enumerate(grades)}
    sink = 1 + len(origins) + len(grades)
    network = _MinCostFlow(sink + 1)

    for o in origins:
        network.add(source, origin_node[o], origin_targets.get(o, 0), 0)
    for g in grades:
        network.add(grade_node[g], sink, grade_targets.get(g, 0), 0)

    base = total + 1
    count = len(cells)
    scale = base ** count
    for i, (o, g) in enumerate(cells):
        received = actual[(o, g)]
        weight = base ** (count - 1 - i)
        # First `received` units reduce L1 by one; further units increase it.
        network.add(origin_node[o], grade_node[g], received, -scale + weight)
        network.add(origin_node[o], grade_node[g], total, scale + weight)

    flow, _ = network.send(source, sink, total)
    if flow != total:
        raise AllocationInfeasible({
            'feasible': False,
            'code': 'flow_shortfall',
            'message': '容量不足，两套目标无法同时达标。',
            'blocking': ['支撑格子容量不足'],
            'individually_reachable': True,
            'simultaneous_feasible': False,
        })

    # Recover flow on the forward origin -> grade arcs.  Arc pairs were added
    # in order, so index 0 is the discounted arc and index 1 the surplus arc.
    allocation = {(o, g): 0 for o in origins for g in grades}
    for i, (o, g) in enumerate(cells):
        received = actual[(o, g)]
        edges = [e for e in network.graph[origin_node[o]]
                 if e[0] == grade_node[g]]
        used_first = received - edges[0][1]
        used_second = total - edges[1][1]
        allocation[(o, g)] = used_first + used_second
    return allocation


def allocate(samples, origin_targets, grade_targets):
    """Return diagnostics and, when feasible, the optimal allocation."""
    diagnostics = diagnose(samples, origin_targets, grade_targets)
    if not diagnostics['feasible']:
        raise AllocationInfeasible(diagnostics)

    actual = {}
    for sample in samples:
        cell = (sample['origin'], sample['grade'])
        actual[cell] = actual.get(cell, 0) + 1
    origins = sorted({s['origin'] for s in samples} | set(origin_targets))
    grades = sorted({s['grade'] for s in samples} | set(grade_targets))

    allocation = _solve(origins, grades, actual, origin_targets, grade_targets)
    objective = sum(abs(allocation[cell] - actual.get(cell, 0))
                    for cell in allocation)
    return {
        'diagnostics': diagnostics,
        'origins': origins,
        'grades': grades,
        'actual': _matrix(origins, grades, actual),
        'allocation': _matrix(origins, grades, allocation),
        'objective': objective,
        'allocation_map': allocation,
        'actual_map': actual,
        'cells': cells_sorted(origins, grades, actual, allocation),
    }


def cells_sorted(origins, grades, actual, allocation):
    """Cells in the canonical (origin, grade) lexicographic order."""
    return [{'origin': o, 'grade': g,
             'received': actual.get((o, g), 0),
             'allocated': allocation.get((o, g), 0),
             'difference': abs(allocation.get((o, g), 0) - actual.get((o, g), 0))}
            for o in origins for g in grades]


def weighted_distribution(samples, allocation, actual, total):
    """Split every cell allocation equally over the samples in that cell."""
    if total <= 0:
        raise ValueError('目标总份数为 0，无法计算加权分布')
    weighted = []
    for sample in samples:
        cell = (sample['origin'], sample['grade'])
        received = actual[cell]
        weight = Fraction(allocation[cell], received)
        weighted.append((float(sample['values']['moisture']),
                         weight, sample['source_key']))
    weighted.sort(key=lambda row: (row[0], row[2]))

    grouped = []
    cumulative = Fraction(0)
    for value, weight, _ in weighted:
        cumulative += weight
        if grouped and grouped[-1][0] == value:
            grouped[-1][1] = cumulative
        else:
            grouped.append([value, cumulative])
    points = [[value, float(cumulative / total)] for value, cumulative in grouped]

    def quantile(p):
        target = Fraction(p) * total
        for value, cumulative in grouped:
            if cumulative >= target:
                return value
        return grouped[-1][0]

    mean = sum(value * weight for value, weight, _ in weighted) / total
    quantiles = {'最小值': quantile(0), 'P25': quantile(Fraction(1, 4)),
                 '中位数': quantile(Fraction(1, 2)),
                 'P75': quantile(Fraction(3, 4)), '最大值': quantile(1)}
    return {
        'points': points,
        'quantiles': quantiles,
        'mean': float(mean),
        'weight_sum': float(sum(weight for _, weight, _ in weighted)),
        'weight_sum_exact': str(sum(weight for _, weight, _ in weighted)),
        'cdf_final': points[-1][1] if points else 0.0,
    }, weighted


def verify_calibration(result):
    """Cross-check weights and cumulative distribution before activation."""
    total = result['total']
    origins = result['origins']
    grades = result['grades']
    allocated = sum(sum(row) for row in result['allocated'])
    if allocated != total:
        raise ValueError('校准份数合计与目标总份数不一致')
    for i, origin in enumerate(origins):
        if sum(result['allocated'][i]) != result['origin_targets'].get(origin, 0):
            raise ValueError(f'产地 {origin} 目标份数未达标')
    for j, grade in enumerate(grades):
        got = sum(result['allocated'][i][j] for i in range(len(origins)))
        if got != result['grade_targets'].get(grade, 0):
            raise ValueError(f'等级 {grade} 目标份数未达标')
    if sum(result['origin_targets'].values()) != total:
        raise ValueError('产地目标合计与总份数不一致')
    if sum(result['grade_targets'].values()) != total:
        raise ValueError('等级目标合计与总份数不一致')
    weighted = result['weighted']
    if abs(weighted['weight_sum'] - total) > 1e-9:
        raise ValueError('权重合计与目标总份数不一致')
    if weighted['points']:
        last = weighted['points'][-1][1]
        if abs(last - 1.0) > 1e-9:
            raise ValueError('累计分布没有收敛到 1')
    previous = -1.0
    for _, cumulative in weighted['points']:
        if not previous <= cumulative <= 1 + 1e-12:
            raise ValueError('累计比例不单调或越界')
        previous = cumulative
    for cell in result['cells']:
        if cell['allocated'] < 0:
            raise ValueError('出现负份数')


def unweighted_distribution(samples):
    values = sorted(float(s['values']['moisture']) for s in samples)

    def quantile(p):
        if len(values) == 1:
            return values[0]
        position = Fraction(p) * (len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        fraction = position - lower
        return values[lower] + float(fraction) * (values[upper] - values[lower])

    return {'count': len(values), 'mean': sum(values) / len(values),
            'quantiles': {'最小值': quantile(0), 'P25': quantile(Fraction(1, 4)),
                          '中位数': quantile(Fraction(1, 2)),
                          'P75': quantile(Fraction(3, 4)), '最大值': quantile(1)}}
