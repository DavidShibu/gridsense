"""Deterministic EV station, deadline scheduler and demand analytics (no I/O)."""
import math
import random
import logging
import json
from pathlib import Path
from dataclasses import dataclass, asdict

try:
    import acn_data
except ImportError:
    acn_data = None

LOG = logging.getLogger(__name__)

SAFETY_FACTOR = 0.95


def site_limit_kw(state):
    """Rated site capacity remains visible; 5% is reserved from all EV plans."""
    return max(0.0, state['capacity_kw'] * SAFETY_FACTOR)


def edf_key(ev, now):
    # Do not let an already impossible request starve a still-feasible deadline.
    impossible = ev['remaining_kwh'] > max(0, ev['departure']-now)*ev['max_kw'] + 1e-6
    return (impossible, ev['departure'], ev['arrival'], ev['id'])


@dataclass
class Vehicle:
    id: str
    arrival: float
    departure: float
    capacity: float
    soc: float
    target: float
    max_kw: float = 7.0
    charger: str | None = None
    status: str = "scheduled"
    power_kw: float = 0.0
    delivered_kwh: float = 0.0

    @property
    def remaining(self):
        return max(0.0, (self.target - self.soc) * self.capacity)


def demo_vehicles():
    # Explicitly synthetic; more vehicles than sockets demonstrates queuing.
    return [Vehicle("EV1", 0, 3, 40, .40, .70),
            Vehicle("EV2", 0, 2, 40, .50, .90),
            Vehicle("EV3", .25, 4, 50, .40, .65),
            Vehicle("EV4", .5, 2.5, 30, .60, .80),
            Vehicle("EV5", 1, 5, 60, .50, .70),
            Vehicle("EV6", 2, 6, 40, .30, .60)]


class Station:
    def __init__(self, vehicles=None, chargers=2, capacity_kw=10.0):
        self.vehicles = demo_vehicles() if vehicles is None else vehicles
        self.chargers = [f"C{i+1}" for i in range(chargers)]
        self.capacity_kw = capacity_kw
        self.base_kw = 1.0
        self.hour = 0.0
        self.sequence = 0
        self.command_sequence = -1
        self.command = {}
        self.command_until = -1.0
        self.last_applied_sequence = -1
        self.refresh()

    def refresh(self):
        for ev in self.vehicles:
            if self.hour >= ev.departure:
                ev.status = "departed"
                ev.charger = None
                ev.power_kw = 0
            elif ev.remaining < 1e-8:
                ev.status = "complete"
                ev.charger = None
                ev.power_kw = 0
            elif self.hour >= ev.arrival and ev.charger is None:
                ev.status = "queued"

    def snapshot(self):
        self.refresh()
        rows = []
        for ev in self.vehicles:
            row = asdict(ev)
            row["remaining_kwh"] = round(ev.remaining, 6)
            rows.append(row)
        return {"sequence": self.sequence, "hour": self.hour,
                "capacity_kw": self.capacity_kw, "base_kw": self.base_kw,
                "operating_limit_kw": self.capacity_kw * SAFETY_FACTOR,
                "chargers": self.chargers, "vehicles": rows,
                "load_kw": self.base_kw + sum(e.power_kw for e in self.vehicles),
                "applied_sequence": self.last_applied_sequence,
                "source": getattr(self, 'data_source', 'synthetic-fallback')}

    def accept(self, command):
        # A whole-station plan is validated before any actuator state changes.
        seq = command["sequence"]
        if not isinstance(seq, int) or seq <= self.command_sequence or seq != self.sequence:
            return False
        assignments = command["assignments"]
        seen_ev, seen_charger = set(), set()
        total = 0.0
        by_id = {e.id: e for e in self.vehicles}
        for a in assignments:
            ev = by_id.get(a["ev_id"])
            rate = float(a["rate_kw"])
            if (ev is None or a["charger_id"] not in self.chargers
                    or ev.id in seen_ev or a["charger_id"] in seen_charger
                    or not math.isfinite(rate) or rate < 0 or rate > ev.max_kw
                    or not ev.arrival <= self.hour < ev.departure or ev.remaining <= 0):
                return False
            seen_ev.add(ev.id)
            seen_charger.add(a["charger_id"])
            total += rate
        if total > max(0, self.capacity_kw * SAFETY_FACTOR - self.base_kw) + 1e-9:
            return False
        self.command = {a["ev_id"]: dict(a) for a in assignments}
        self.command_sequence = seq
        self.last_applied_sequence = seq
        self.command_until = self.hour + 0.1
        for ev in self.vehicles:
            a = self.command.get(ev.id)
            ev.charger = a["charger_id"] if a else None
            ev.power_kw = a["rate_kw"] if a else 0.0
            if a:
                ev.status = "charging" if ev.power_kw > 0 else "connected"
        self.refresh()
        return True

    def step(self, hours):
        if not math.isfinite(hours) or hours <= 0:
            raise ValueError("hours must be positive and finite")
        # Clamp locally even if supply changes after a command was accepted.
        total = sum(a["rate_kw"] for a in self.command.values())
        scale = min(1, max(0, self.capacity_kw*SAFETY_FACTOR-self.base_kw) / total) if total else 0
        for ev in self.vehicles:
            a = self.command.get(ev.id)
            duration = max(0, min(hours, ev.departure-self.hour,
                                  self.command_until-self.hour))
            if a and duration > 0 and ev.arrival <= self.hour and ev.remaining > 0:
                taper = min(1, max(0, (1-ev.soc)/.2))
                power = min(ev.max_kw, a["rate_kw"]) * scale * taper
                energy = min(ev.remaining, power * duration)
                ev.soc += energy / ev.capacity
                ev.delivered_kwh += energy
                ev.power_kw = energy / hours
            else:
                ev.power_kw = 0
            if ev.charger is not None:
                ev.status = "charging" if ev.power_kw > 0 else "connected"
        self.hour += hours
        self.sequence += 1
        self.refresh()


def tou_demo_station(unmanaged=False):
    """Feasible peak-to-off-peak scenario; separate from the overloaded original demo."""
    station = Station([
        Vehicle('EV1', 16, 18, 40, .3, .4),
        Vehicle('EV2', 16, 24, 40, .3, .6),
    ], capacity_kw=100 if unmanaged else 10)
    station.hour = 16.
    return station


def historical_sessions(days=28, seed=42):
    """Independent synthetic training days with morning/evening arrival peaks."""
    rng = random.Random(seed)
    rows = []
    for day in range(days):
        for hour in range(24):
            count = max(0, round((4 if hour in (8, 9, 17, 18) else 1) + rng.gauss(0, 1)))
            for _ in range(count):
                rows.append({"day": day, "hour": hour,
                             "energy_kwh": rng.uniform(5, 20)})
    return rows


def real_or_synthetic_history(days=42, prefer_real=True):
    if prefer_real and acn_data is not None:
        try:
            if acn_data.LOCAL_DIR.exists():
                sessions = acn_data.saved_sessions(for_history=True, days=days)
            else:
                start, end = acn_data.recent_window(days)
                sessions = acn_data.fetch_sessions(start=start, end=end)
            rows = acn_data.to_demand_samples(sessions)
            active_days = {r['day'] for r in rows}
            if len(active_days) < 18:
                raise ValueError('fewer than 18 days with observed sessions')
            # The API query covers complete local days. Missing hourly arrivals
            # inside that fully fetched interval are observed zeros, not fake sessions.
            bins = {(r['day'], r['hour']): r['energy_kwh'] for r in rows}
            dense = [{'dataset': 'acn-caltech-v1', 'day': d, 'hour': h,
                      'energy_kwh': bins.get((d, h), 0.0), 'source': 'acn-data-caltech'}
                     for d in range(max(active_days)+1) for h in range(24)]
            LOG.warning('Using ACN-Data history: %d sessions, %d complete hourly days', len(sessions), len(dense)//24)
            # Export only derived fleet parameters for a paho-only sensor laptop.
            fleet = acn_data.to_vehicle_sessions(sessions)
            if fleet:
                target = Path(__file__).with_name('acn_vehicles.json')
                target.write_text(json.dumps({'source': 'acn-data-caltech', 'vehicles': [asdict(v) for v in fleet]}), encoding='utf-8')
            return dense
        except Exception as exc:
            # Never include provider exception text, URLs or credentials in logs.
            LOG.warning('[FALLBACK] Using synthetic history (%s)', type(exc).__name__)
    else:
        LOG.warning('[FALLBACK] Using synthetic history (%s)', 'forced offline' if not prefer_real else 'ACN module unavailable')
    return historical_sessions(days, seed=42)


def real_or_synthetic_vehicles(prefer_real=True):
    if prefer_real and acn_data is not None:
        try:
            if acn_data.LOCAL_DIR.exists():
                sessions = acn_data.saved_sessions()
            else:
                start, end = acn_data.recent_window(7)
                sessions = acn_data.fetch_sessions(start=start, end=end)
            fleet = acn_data.to_vehicle_sessions(sessions)
            if fleet:
                return fleet[:6]
            raise ValueError('No usable ACN vehicles')
        except Exception as exc:
            LOG.warning('[FALLBACK] Using synthetic vehicles (%s)', type(exc).__name__)
    elif prefer_real:
        # A copied sender/ folder has no data-access packages or token. It can
        # replay the explicitly exported fleet from the project laptop instead.
        try:
            payload = json.loads(Path(__file__).with_name('acn_vehicles.json').read_text(encoding='utf-8'))
            fleet = [Vehicle(**row) for row in payload['vehicles'][:6]]
            if payload.get('source') != 'acn-data-caltech' or not fleet:
                raise ValueError('Invalid prepared fleet')
            for vehicle in fleet:
                if not (vehicle.departure > vehicle.arrival and vehicle.capacity > 0 and 0 <= vehicle.soc <= vehicle.target <= 1 and 0 < vehicle.max_kw <= 7):
                    raise ValueError('Invalid prepared vehicle')
                vehicle.data_source = 'acn-data-caltech'
            return fleet
        except (OSError, ValueError, KeyError, TypeError):
            LOG.warning('[FALLBACK] Using synthetic vehicles (no prepared ACN fleet)')
    else:
        LOG.warning('[FALLBACK] Using synthetic vehicles (forced offline)')
    return demo_vehicles()


def demand_model():
    """Hourly seasonal-mean regression, evaluated on held-out whole days."""
    rows = historical_sessions()
    bins = [[0.0]*24 for _ in range(28)]
    counts = [0]*24
    for r in rows:
        bins[r["day"]][r["hour"]] += r["energy_kwh"]
        counts[r["hour"]] += 1
    profile = [sum(d[h] for d in bins[:21])/21 for h in range(24)]
    baseline = sum(profile)/24
    errors = [abs(day[h]-profile[h]) for day in bins[21:] for h in range(24)]
    naive = [abs(day[h]-baseline) for day in bins[21:] for h in range(24)]
    return {"profile_kwh": profile, "arrivals_per_hour": [n/28 for n in counts],
            "mae_kwh": sum(errors)/len(errors), "baseline_mae_kwh": sum(naive)/len(naive),
            "training_days": 21, "test_days": 7,
            "source": "seeded synthetic history; not a real-world accuracy claim"}


def schedule(state, model=None):
    model = demand_model() if model is None else model
    now = state["hour"]
    active = [e for e in state["vehicles"]
              if e["arrival"] <= now < e["departure"] and e["remaining_kwh"] > 1e-8]
    active.sort(key=lambda e: edf_key(e, now))
    available = max(0.0, site_limit_kw(state)-state["base_kw"])
    forecast = model["profile_kwh"][int(now+1) % 24]
    typical = sum(model["profile_kwh"])/24
    # Forecasted busy periods cause feasible sessions to charge earlier.
    reserve_factor = 1.25 if forecast > typical else 1.0
    assignments, alerts = [], []
    for e in active:
        if e["remaining_kwh"] > (e["departure"]-now)*e["max_kw"] + 1e-6:
            alerts.append(f'{e["id"]}: cannot meet target before departure at maximum rate')
    for deadline in sorted({e["departure"] for e in active}):
        needed = sum(e["remaining_kwh"] for e in active if e["departure"] <= deadline)
        if needed > available*(deadline-now) + 1e-6:
            alerts.append("Shared supply cannot meet all current deadlines")
            break
    for charger, e in zip(state["chargers"], active):
        # Work-conserving EDF: finish the first feasible deadline before
        # spreading scarce power across later requests.
        rate = min(e["max_kw"], available)
        rate = math.floor(max(0, rate)*100)/100
        available -= rate
        assignments.append({"charger_id": charger, "ev_id": e["id"], "rate_kw": rate})
    for e in state["vehicles"]:
        if e["status"] == "departed" and e["remaining_kwh"] > .01:
            alerts.append(f'{e["id"]}: departed with {e["remaining_kwh"]:.2f} kWh unmet')
    return {"sequence": state["sequence"], "assignments": assignments,
            "alerts": alerts, "forecast_next_hour_kwh": forecast,
            "forecast_factor": reserve_factor, "analytics": model,
            "operating_limit_kw": site_limit_kw(state),
            "reason": "Feasibility-aware EDF; impossible requests get best effort; 5% site reserve"}
