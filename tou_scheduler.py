"""Receding-horizon cost minimization with hard energy/deadline/socket constraints.

Only the first control interval is applied. Replan from committed telemetry.
Infeasible requests or solver failures use the existing best-effort EDF plan.
"""
import math
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from station_core import site_limit_kw
from tariff import price_at

CONTROL_HOURS = 1 / 30  # Must match simulator.py's two simulated minutes.


def apply_tou(state, plan, previous=None, enabled=True, time_limit=.5):
    now = state['hour']
    plan.update(price_per_kwh=price_at(now), price_currency='INR',
                tariff_profile=[price_at(h) for h in range(24)])
    if not enabled:
        plan['tou_status'] = 'disabled'
        return plan
    vehicles = [e for e in state['vehicles'] if e['departure'] > now
                and e['remaining_kwh'] > 1e-8]
    if not vehicles:
        plan.update(tou_status='idle', assignments=[])
        return plan
    available = max(0., site_limit_kw(state) - state['base_kw'])

    def fallback(reason):
        plan['tou_status'] = 'fallback_edf'
        plan['alerts'].append('ToU: ' + reason + '; using best-effort deadline scheduling')
        return plan

    # Conservative lower bound on taper efficiency until each vehicle's target.
    efficiency = [min(1., max(0., (1. - e['target']) / .2)) for e in vehicles]
    for e, eta in zip(vehicles, efficiency):
        if e['remaining_kwh'] > max(0., e['departure']-max(now, e['arrival'])) * min(e['max_kw'], available) * eta + 1e-6:
            return fallback('deadline feasibility cannot be certified (energy/rate/taper)')
    end = max(e['departure'] for e in vehicles)
    if end - now > 48 or len(vehicles) > 30:
        return fallback('planning horizon exceeds demo limits')
    # First interval matches the actuator cadence; later intervals <=15 minutes.
    first_end = min(now + CONTROL_HOURS, end)
    boundaries = {now, first_end, end}
    boundaries.update(t / 4 for t in range(math.ceil(first_end * 4), math.ceil(end * 4))
                      if first_end < t / 4 < end)
    for e in vehicles:
        boundaries.update(t for t in (e['arrival'], e['departure']) if first_end < t < end)
    edges = sorted(boundaries)
    durations = np.diff(edges)
    n, slots = len(vehicles), len(durations)
    count = n * slots
    # p[i,t] commanded kW and binary z[i,t] socket occupancy.
    upper = np.zeros(2 * count)
    objective = np.zeros(2 * count)
    for i, e in enumerate(vehicles):
        for t, duration in enumerate(durations):
            k = i * slots + t
            if e['arrival'] <= edges[t] + 1e-9 and edges[t+1] <= e['departure'] + 1e-9:
                upper[k], upper[count+k] = e['max_kw'], 1
            # Earlier charging wins equal-price ties. Physical load may taper below command.
            objective[k] = duration * (price_at(edges[t] + 1e-8) + 1e-4 * (edges[t]-now))
            objective[count+k] = 1e-7
    matrix = lil_matrix((n + 2 * slots + count, 2 * count))
    lower = np.full(matrix.shape[0], -np.inf)
    limit = np.zeros(matrix.shape[0])
    for i, e in enumerate(vehicles):
        matrix[i, i*slots:(i+1)*slots] = durations * efficiency[i]
        lower[i] = e['remaining_kwh']
        limit[i] = np.inf
    for t in range(slots):
        for i in range(n):
            k = i * slots + t
            matrix[n+t, k] = 1
            matrix[n+slots+t, count+k] = 1
        limit[n+t] = available
        limit[n+slots+t] = len(state['chargers'])
    for k in range(count):
        row = n + 2*slots + k
        matrix[row, k] = 1
        matrix[row, count+k] = -vehicles[k // slots]['max_kw']
    try:
        result = milp(objective, integrality=np.r_[np.zeros(count), np.ones(count)],
                      bounds=Bounds(np.zeros(2*count), upper),
                      constraints=LinearConstraint(matrix.tocsc(), lower, limit),
                      options={'time_limit': time_limit, 'mip_rel_gap': .001})
    except (ValueError, RuntimeError):
        return fallback('optimizer error')
    if result.x is None or not np.all(np.isfinite(result.x)):
        return fallback('no feasible plan returned within solver budget')
    # Validate even time-limited incumbents before relying on deadline feasibility.
    values = matrix @ result.x
    if (np.any(values < lower - 1e-6) or np.any(values > limit + 1e-6)
            or np.any(result.x < -1e-6) or np.any(result.x > upper + 1e-6)
            or np.any(abs(result.x[count:] - np.round(result.x[count:])) > 1e-6)):
        return fallback('solver result failed constraint validation')
    chosen = [(e, max(0., float(result.x[i*slots]))) for i, e in enumerate(vehicles)
              if result.x[i*slots] > 1e-7]
    if len(chosen) > len(state['chargers']):
        return fallback('invalid first-interval socket allocation')
    old = {a['ev_id']: a['charger_id'] for a in (previous or {}).get('assignments', [])}
    sockets = {e['id']: old[e['id']] for e, _ in chosen if old.get(e['id']) in state['chargers']}
    free = [c for c in state['chargers'] if c not in sockets.values()]
    assignments = []
    remaining = available
    for e, rate in chosen:
        # Only remove solver floating-point overshoot; do not round to 0.01 kW.
        rate = min(rate, remaining, e['max_kw'])
        remaining -= rate
        socket = sockets.get(e['id']) or free.pop(0)
        assignments.append({'ev_id': e['id'], 'charger_id': socket, 'rate_kw': rate})
    plan.update(assignments=assignments, tou_status='optimal' if result.success else 'feasible_time_limit',
                reason='Minimum tariff cost subject to known deadlines, site capacity and socket limits',
                planned_cost_upper_bound=float(np.dot(objective[:count], result.x[:count])),
                stability_policy={'override': 'ToU feasibility; preserve existing socket where possible'},
                assigned_since={e['id']: (previous or {}).get('assigned_since', {}).get(e['id'], now)
                                for e, _ in chosen})
    return plan
