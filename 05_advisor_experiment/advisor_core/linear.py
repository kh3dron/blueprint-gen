"""Small primal simplex for max c*x, A*x <= b, x >= 0 with b >= 0.

Material balances have nonnegative right-hand sides (external supply), so the
all-idle solution is feasible and no phase-I or external dependency is needed.
Bland's pivot rule makes degenerate shared-input cases deterministic.
"""
import math


EPS = 1e-9


def maximize(objective, constraints, bounds):
    n, m = len(objective), len(bounds)
    if len(constraints) != m or any(len(row) != n for row in constraints):
        raise ValueError("linear-program dimensions do not match")
    if any(not math.isfinite(v) for row in constraints for v in row) or any(
        not math.isfinite(v) for v in list(objective) + list(bounds)
    ):
        raise ValueError("linear program contains non-finite values")
    if any(v < 0 for v in bounds):
        raise ValueError("this solver requires nonnegative right-hand sides")
    rows = [list(map(float, row)) + [float(i == j) for j in range(m)] + [float(bounds[i])]
            for i, row in enumerate(constraints)]
    rows.append([-float(v) for v in objective] + [0.0] * (m + 1))
    basis = list(range(n, n + m))
    for _ in range(10000):
        entering = next((j for j in range(n + m) if rows[-1][j] < -EPS), None)
        if entering is None:
            result = [0.0] * n
            for i, variable in enumerate(basis):
                if variable < n:
                    result[variable] = max(0.0, rows[i][-1])
            # Check the result independently of the tableau before exposing it as a bound.
            if any(sum(a * x for a, x in zip(row, result)) > b + 1e-6 * max(1, abs(b))
                   for row, b in zip(constraints, bounds)):
                raise ArithmeticError("linear solve failed its feasibility check")
            return result
        candidates = [(rows[i][-1] / rows[i][entering], basis[i], i)
                      for i in range(m) if rows[i][entering] > EPS]
        if not candidates:
            raise ValueError("unbounded linear program")
        best_ratio = min(r for r, _, _ in candidates)
        leaving = min((b, i) for r, b, i in candidates if abs(r - best_ratio) <= EPS)[1]
        pivot = rows[leaving][entering]
        rows[leaving] = [v / pivot for v in rows[leaving]]
        for i in range(m + 1):
            if i != leaving:
                factor = rows[i][entering]
                rows[i] = [v - factor * p for v, p in zip(rows[i], rows[leaving])]
        basis[leaving] = entering
    raise ArithmeticError("linear solve exceeded the pivot limit")
