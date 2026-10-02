"""Validation-only population tuning; no final holdout or deployment writes.

Generate operating points from each population's benign tail, then check every
seed/size through the production resolver. P95 is descriptive, never a waiver
for a population that exceeds the published FPR budget.
"""

from __future__ import annotations

import math

from . import sweep as SW

MIN_POPULATIONS = 20
BUDGETS = {
    "warn_fpr": SW.WARN_FPR_BUDGET,
    "challenge_fpr": SW.CHALLENGE_FPR_BUDGET,
    "block_fpr": SW.BLOCK_FPR_BUDGET,
}


def validate_seeds(seeds, *, reserved):
    seeds = list(seeds)
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate validation seeds")
    if len(seeds) < MIN_POPULATIONS:
        raise ValueError(f"at least {MIN_POPULATIONS} validation populations required")
    overlap = sorted(set(seeds) & set(reserved))
    if overlap:
        raise ValueError(f"reserved/spent holdout seeds cannot be tuned: {overlap}")
    return sorted(seeds)


def validate_grid(groups):
    seeds = validate_seeds({s for s, _ in groups}, reserved=())
    sizes = sorted({n for _, n in groups})
    if any(n <= 0 for n in sizes):
        raise ValueError("history sizes must be positive")
    expected = {(s, n) for s in seeds for n in sizes}
    if set(groups) != expected:
        raise ValueError("incomplete population/size grid")
    return seeds, sizes


def _quantile(values, p):
    values = sorted(values)
    if not values:
        raise ValueError("empty population")
    position = (len(values) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def threshold_candidates(groups, *, n_points=12):
    if not groups or n_points < 2:
        raise ValueError("normal populations and at least two grid points required")
    for values in groups.values():
        if not values or any(not math.isfinite(x) or not 0 <= x <= 1 for x in values):
            raise ValueError("normal scores must be nonempty and finite in [0, 1]")

    def tail(fpr):
        # Equal population weight: a large benign cell cannot mask a small one.
        # Retain each size's P95 and worst population as separate candidates.
        by_size = {}
        for (_, size), values in groups.items():
            by_size.setdefault(size, []).append(_quantile(values, 1 - fpr))
        return (
            max(_quantile(v, 0.95) for v in by_size.values()),
            max(max(v) for v in by_size.values()),
        )

    out = set()
    for i in range(n_points):
        fpr = SW.CHALLENGE_FPR_BUDGET * (0.2 + 1.8 * i / (n_points - 1))
        for block_factor in (0.25, 0.5):
            for warn_factor in (3.0, 6.0):
                tails = (
                    tail(min(fpr * warn_factor, SW.WARN_FPR_BUDGET)),
                    tail(fpr),
                    tail(max(fpr * block_factor, 1e-6)),
                )
                for population_stat in (0, 1):
                    # Production uses >=. Move strictly above ties, preserving
                    # full precision; rounding back down silently increases FPR.
                    point = tuple(
                        min(1.0, math.nextafter(v[population_stat], math.inf))
                        for v in tails
                    )
                    if point[0] <= point[1] <= point[2] <= 1.0:
                        out.add(point)
    return [dict(zip(("warn", "challenge", "block"), p)) for p in sorted(out)]


def population_report(cells):
    groups = {(c.seed, c.size): c for c in cells}
    if len(groups) != len(cells):
        raise ValueError("duplicate population/size cells")
    seeds, sizes = validate_grid(groups)
    violations = []
    per_size = {}
    for size in sizes:
        per_size[str(size)] = {}
        for metric, budget in BUDGETS.items():
            rates = []
            for seed in seeds:
                values = list(
                    getattr(groups[(seed, size)], "per_user_" + metric).values()
                )
                if not values or any(
                    not math.isfinite(x) or not 0 <= x <= 1 for x in values
                ):
                    raise ValueError(
                        f"missing/invalid benign rates for seed{seed}_size{size}"
                    )
                rate = sum(values) / len(values)
                rates.append(rate)
                if rate > budget:
                    violations.append(f"seed{seed}_size{size}_{metric}")
            per_size[str(size)][metric] = {
                "p95": _quantile(rates, 0.95),
                "worst": max(rates),
                "budget": budget,
                "n_populations": len(rates),
            }
    return {"eligible": not violations, "violations": violations, "per_size": per_size}


def search(records, *, gamma, n_points=12):
    from . import tune as TU

    seeds, sizes = validate_grid(records)
    if not math.isfinite(gamma) or not 0 <= gamma <= 1:
        raise ValueError("gamma must be finite in [0, 1]")
    normals = {}
    for key, rows in records.items():
        if any(r.resolver is None or r.fixed_decision is not None for r in rows):
            raise ValueError("population tuning requires hybrid ResolverInput records")
        normals[key] = [r.resolver.final_score for r in rows if not r.is_attack]
        if not any(r.is_attack for r in rows):
            raise ValueError(f"missing attack validation events in {key}")

    def evaluate(thresholds):
        cells = [
            TU.stat_direct(rows, seed, size, thresholds)
            for (seed, size), rows in sorted(records.items())
        ]
        return {"metrics": TU.macro(cells), "population": population_report(cells)}

    candidates = threshold_candidates(normals, n_points=n_points)
    points = [{"gamma": gamma, "thresholds": t, **evaluate(t)} for t in candidates]
    eligible = [
        p
        for p in points
        if p["population"]["eligible"] and SW.eligible(p["metrics"])[0]
    ]
    best = (
        max(
            eligible,
            key=lambda p: (
                p["metrics"]["recall_challenge"],
                p["metrics"]["recall"],
                p["metrics"]["precision"],
            ),
        )
        if eligible
        else None
    )
    floor = evaluate({"warn": 1.01, "challenge": 1.01, "block": 1.01})
    return {
        "status": "validation_candidate" if best else "validation_failed",
        "deploy_ready": False,
        "split": "validation-tuning",
        "validation_seeds": seeds,
        "sizes": sizes,
        "gamma": gamma,
        "selection_rule": "every seed/size FPR budget -> recall_challenge -> recall -> precision",
        "n_candidates": len(points),
        "n_eligible": len(eligible),
        "best": best,
        "policy_floor": floor["population"],
        "points": points,
    }
