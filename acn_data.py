"""ACN-Data access, bounded caching, and explicitly model-derived battery SoC.

ACNPortal's published API is DataClient(token).get_sessions(...), not a module
function. Battery specifications are optional; ACN does not normally identify cars.
"""
import hashlib
import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime, format_datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:
    requests = None
try:
    from acnportal.acndata import DataClient
except ImportError:
    DataClient = None

LOG = logging.getLogger(__name__)
CACHE_PATH = Path(__file__).with_name('artifacts')/'acn_cache.json'
CACHE_TTL = 24*60*60
LOCAL_DIR = Path(__file__).with_name('data')/'acn_downloads'
API = 'https://ev.caltech.edu/api/v1/'
_client_lock = threading.Lock()


class AcnDataError(RuntimeError):
    pass


class AcnDataNotConfigured(AcnDataError):
    pass


def _token(value=None):
    value = value if value is not None else os.environ.get('ACN_DATA_TOKEN')
    if not value:
        raise AcnDataNotConfigured('ACN_DATA_TOKEN is not configured')
    return value


def _datetime(value):
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            result = parsedate_to_datetime(str(value))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _local(session, field):
    return _datetime(session[field]).astimezone(ZoneInfo(session.get('timezone', 'America/Los_Angeles')))


def _read_cache():
    try:
        data = json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_get(key):
    record = _read_cache().get(key, {})
    age = time.time()-record.get('fetched_at', 0)
    return record.get('data') if 0 <= age < CACHE_TTL else None


def _cache_put(key, data):
    records = {k: v for k, v in _read_cache().items()
               if 0 <= time.time()-v.get('fetched_at', 0) < CACHE_TTL}
    records[key] = {'fetched_at': time.time(), 'data': data}
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE_PATH.with_suffix('.tmp')
        temporary.write_text(json.dumps(records, default=lambda x: x.isoformat(), allow_nan=False), encoding='utf-8')
        temporary.replace(CACHE_PATH)
    except OSError:
        LOG.warning('ACN cache could not be written; continuing without disk cache')


def _get(url, **kwargs):
    if requests is None:
        raise AcnDataNotConfigured('Install project requirements to enable ACN-Data access')
    response = requests.get(url, timeout=(5, 20), **kwargs)
    response.raise_for_status()
    return response


def _current_values(session):
    series = session.get('chargingCurrent') or {}
    values = series.get('current', []) if isinstance(series, dict) else series
    if values and isinstance(values[0], dict):
        values = [point.get('current', point.get('value', 0)) for point in values]
    return [max(0.0, float(value)) for value in values if math.isfinite(float(value))]


def _clean_session(session):
    cleaned = {k: session[k] for k in ('sessionID', 'connectionTime', 'disconnectTime',
               'kWhDelivered', 'chargingCurrent', 'timezone', 'make', 'model', 'year') if k in session}
    cleaned['userInputs'] = [{'kWhRequested': r['kWhRequested']} for r in
                             (session.get('userInputs') or []) if 'kWhRequested' in r]
    return cleaned


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, default=lambda x: x.isoformat(), allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def saved_sessions(for_history=False, days=42):
    """Read durable downloads without a token. Partial days are live-demo only."""
    records = []
    for path in sorted(LOCAL_DIR.glob('caltech-*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('site') != 'caltech':
                continue
            day = datetime.strptime(record['day'], '%Y-%m-%d').date()
            valid = []
            for session in record['sessions']:
                if _local(session, 'connectionTime').date() != day:
                    raise ValueError('Session outside saved day')
                energy = float(session['kWhDelivered'])
                if math.isfinite(energy) and energy >= .5 and max(_current_values(session), default=0) > 0:
                    valid.append(session)
            records.append((day, record.get('complete') is True, valid))
        except (OSError, ValueError, TypeError, KeyError):
            LOG.warning('Ignoring invalid saved ACN day: %s', path.name)
    if not for_history:
        return [s for _, _, sessions in records[-days:] for s in sessions]
    # Do not turn undownloaded days or partial pages into zero demand.
    runs, run = [], []
    for record in records:
        day, complete, _ = record
        if not complete or (run and day-run[-1][0] != timedelta(days=1)):
            if run:
                runs.append(run)
            run = []
        if complete:
            run.append(record)
    if run:
        runs.append(run)
    for run in reversed(runs):
        selected = run[-days:]
        if sum(bool(r[2]) for r in selected) >= 18:
            LOG.warning('Using saved ACN history: %d completely downloaded days', len(selected))
            return [s for _, _, sessions in selected for s in sessions]
    LOG.warning('Saved ACN history is insufficient: need 18 observed days in a completely downloaded interval')
    raise AcnDataError('Saved history needs 18 observed days in a completely downloaded interval')


def download_local(days=42, seconds=120):
    """Resume per-day pages, saving every received session; keep partial progress."""
    credential = _token()
    start, end = recent_window(days)
    deadline = time.monotonic()+seconds
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    day = start
    while day < end and time.monotonic() < deadline:
        path = LOCAL_DIR/('caltech-'+day.date().isoformat()+'.json')
        record = {'site': 'caltech', 'day': day.date().isoformat(), 'complete': False,
                  'next_page': 1, 'sessions': []}
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
        if record['complete']:
            day += timedelta(days=1)
            continue
        until = day+timedelta(days=1)
        cond = f'connectionTime >= "{format_datetime(day.astimezone(timezone.utc), usegmt=True)}" and connectionTime < "{format_datetime(until.astimezone(timezone.utc), usegmt=True)}"'
        try:
            while time.monotonic() < deadline:
                response = _get(API+'sessions/caltech/ts/', auth=(credential, ''),
                                params={'where': cond, 'sort': 'connectionTime', 'max_results': 1,
                                        'page': record['next_page']})
                payload = response.json()
                items = payload['_items']
                if not isinstance(items, list) or '_links' not in payload:
                    raise AcnDataError('Invalid paginated response')
                known = {s['sessionID'] for s in record['sessions']}
                for item in items:
                    clean = _clean_session(item)
                    if clean['sessionID'] not in known:
                        record['sessions'].append(clean)
                        known.add(clean['sessionID'])
                        _write_json(path, record)
                record['next_page'] += 1
                record['complete'] = 'next' not in payload['_links']
                _write_json(path, record)
                LOG.warning('Saved ACN %s: %d sessions (%s)', record['day'], len(record['sessions']),
                            'complete day' if record['complete'] else 'partial day')
                if record['complete']:
                    break
        except Exception as exc:
            LOG.warning('ACN download paused (%s); saved progress retained', type(exc).__name__)
            break
        day = until
    sessions = saved_sessions()
    LOG.warning('Saved usable ACN sessions: %d; folder: %s', len(sessions), LOCAL_DIR)
    return sessions


def fetch_sessions(site='caltech', start=None, end=None, min_kwh=0.5, token=None):
    """Return filtered time-series sessions for an explicitly bounded UTC window."""
    credential = _token(token)  # Never cache credentials, authentication headers or exception text.
    if site not in ('caltech', 'jpl', 'office001'):
        raise ValueError('Unsupported ACN site')
    if start is None or end is None:
        raise ValueError('start and end are required')
    start, end = _datetime(start).astimezone(timezone.utc), _datetime(end).astimezone(timezone.utc)
    if end <= start or end-start > timedelta(days=62):
        raise ValueError('ACN queries must cover more than zero and at most 62 days')
    if not math.isfinite(min_kwh) or min_kwh < 0:
        raise ValueError('min_kwh must be nonnegative')
    key = json.dumps([site, start.isoformat(), end.isoformat()])
    sessions = _cache_get(key)
    if sessions is None:
        if DataClient is None:
            raise AcnDataNotConfigured('acnportal is not installed')
        cond = f'connectionTime >= "{format_datetime(start, usegmt=True)}" and connectionTime <= "{format_datetime(end, usegmt=True)}"'
        try:
            # ACNPortal 0.3.3 has no timeout argument. Scope a timeout-capable
            # transport to its module only; do not change global requests.get.
            with _client_lock, patch('acnportal.acndata.data_client.requests', SimpleNamespace(get=_get)):
                client = DataClient(credential)
                sessions = []
                started = time.monotonic()
                for session in client.get_sessions(site, cond=cond, timeseries=True):
                    if time.monotonic()-started > 300 or len(sessions) >= 5000:
                        raise AcnDataError('ACN query exceeded bounded demo fetch limits')
                    # Strip user identity and unneeded fields before storing or exporting.
                    cleaned = {k: session[k] for k in ('sessionID', 'connectionTime', 'disconnectTime',
                               'kWhDelivered', 'chargingCurrent', 'timezone', 'make', 'model', 'year') if k in session}
                    cleaned['userInputs'] = [{'kWhRequested': row['kWhRequested']} for row in
                                             (session.get('userInputs') or []) if 'kWhRequested' in row]
                    if start <= _datetime(cleaned['connectionTime']) < end:
                        sessions.append(cleaned)
            _cache_put(key, sessions)
        except Exception as exc:
            raise AcnDataError('ACN fetch failed ('+type(exc).__name__+')') from None
    result = []
    for session in sessions:
        try:
            energy = float(session['kWhDelivered'])
            if math.isfinite(energy) and energy >= min_kwh and max(_current_values(session), default=0) > 0:
                result.append(session)
        except (ValueError, TypeError, KeyError):
            continue
    return result


def recent_window(days=42, site='caltech'):
    """Most recent *available* complete site-local days, not the current calendar."""
    credential = _token()
    if not 1 <= days <= 62 or site not in ('caltech', 'jpl', 'office001'):
        raise ValueError('Invalid recent window')
    override = os.environ.get('ACN_DATA_END')
    if override and len(override) == 10:
        end = datetime.strptime(override, '%Y-%m-%d').replace(tzinfo=ZoneInfo('America/Los_Angeles'))
        return end-timedelta(days=days), end
    latest = {'connectionTime': override, 'timezone': 'America/Los_Angeles'} if override else _cache_get('latest:'+site)
    if latest is None:
        try:
            response = _get(API+'sessions/'+site, params={'sort': '-connectionTime', 'max_results': 1}, auth=(credential, ''))
            row = response.json()['_items'][0]
            latest = {'connectionTime': row['connectionTime'], 'timezone': row.get('timezone', 'America/Los_Angeles')}
            _cache_put('latest:'+site, latest)
        except Exception as exc:
            raise AcnDataError('Latest ACN date unavailable ('+type(exc).__name__+')') from None
    end = _local(latest, 'connectionTime').replace(hour=0, minute=0, second=0, microsecond=0)
    return end-timedelta(days=days), end


@lru_cache(maxsize=1)
def _ev_catalog():
    # The supplied website documents an API implementation, not a stable public
    # API hostname. Consume its documented public JSON release over HTTPS.
    release = _get('https://api.github.com/repos/open-ev-data/open-ev-data-dataset/releases/latest').json()
    assets = [a for a in release.get('assets', []) if a['name'].endswith('.json') and 'open-ev-data' in a['name']]
    if not assets:
        raise ValueError('No OpenEV JSON release found')
    payload = _get(assets[0]['browser_download_url']).json()
    return payload.get('vehicles', []) if isinstance(payload, dict) else payload


@lru_cache(maxsize=256)
def battery_capacity_for(make=None, model=None, year=None):
    if make and model and year:
        try:
            matches = [row for row in _ev_catalog() if
                       str(row.get('brand', row.get('make', ''))).casefold() == str(make).casefold()
                       and str(row.get('model', '')).casefold() == str(model).casefold()
                       and str(row.get('year', '')) == str(year)]
            values = {float(row['battery']['pack_capacity_kwh_net']) for row in matches
                      if row.get('battery', {}).get('pack_capacity_kwh_net')}
            if len(values) == 1 and 0 < next(iter(values)) <= 250:
                return values.pop()
        except Exception:
            pass
    LOG.warning('Battery capacity unknown or lookup unavailable; using assumed 40 kWh')
    return 40.0


def simulate_soc_trace(session, capacity_kwh=None, initial_soc=0.3, voltage=208, efficiency=0.9):
    capacity = float(capacity_kwh if capacity_kwh is not None else battery_capacity_for(
        session.get('make'), session.get('model'), session.get('year')))
    energy = float(session['kWhDelivered'])
    if not all(math.isfinite(v) for v in (capacity, energy, initial_soc, voltage, efficiency)) or capacity <= 0 or energy < 0 or voltage <= 0 or not 0 < efficiency <= 1 or not 0 <= initial_soc <= 1:
        raise ValueError('Invalid SoC model inputs')
    arrival, departure = _local(session, 'connectionTime'), _local(session, 'disconnectTime')
    duration = (departure.astimezone(timezone.utc)-arrival.astimezone(timezone.utc)).total_seconds()/3600
    if duration <= 0:
        raise ValueError('Invalid session duration')
    series = session.get('chargingCurrent') or {}
    currents = _current_values(session)
    if not currents or max(currents) <= 0:
        raise ValueError('Missing positive current samples')
    timestamps = series.get('timestamps', []) if isinstance(series, dict) else []
    if timestamps:
        if len(timestamps) != len(currents):
            raise ValueError('Current and timestamp lengths differ')
        times = [_datetime(t).astimezone(timezone.utc) for t in timestamps]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError('Current timestamps must increase')
        # ACN includes logger padding before connection and after disconnect.
        # Integrate only measured samples inside the actual connected interval.
        pairs = [(t, c) for t, c in zip(times, currents)
                 if arrival.astimezone(timezone.utc) <= t <= departure.astimezone(timezone.utc)]
        if len(pairs) < 2 or max(c for _, c in pairs) <= 0:
            raise ValueError('Insufficient current samples inside the session')
        times, currents = map(list, zip(*pairs))
    else:
        # Numeric fixture/legacy traces have an explicitly inferred sample period.
        times = [arrival.astimezone(timezone.utc)+timedelta(hours=duration*i/max(1, len(currents)-1)) for i in range(len(currents))]
    peak = max(currents)
    tail = currents[-max(1, math.ceil(len(currents)*.2)):]
    taper = sum(tail)/len(tail) < .5*peak
    estimate, assumption = initial_soc, 'supplied/default initial SoC'
    requested = next((r.get('kWhRequested') for r in reversed(session.get('userInputs') or [])
                      if r.get('kWhRequested') is not None), None)
    if requested is not None and math.isfinite(float(requested)) and float(requested) >= 0:
        estimate = min(.95, max(.05, 1-float(requested)/capacity))
        assumption = 'inferred from requested energy and assumed full target'
    elif taper:
        estimate = min(.95, max(.05, .95-energy/capacity))
        assumption = 'inferred from observed taper and assumed 95% final SoC'
    final = min(1.0, estimate+energy/capacity)
    weights = [0.0]
    cumulative = 0.0
    for i in range(1, len(currents)):
        dt = (times[i]-times[i-1]).total_seconds()/3600
        provisional = estimate+cumulative/capacity
        # Preserve already-observed taper; otherwise apply a simple CV shape.
        factor = 1.0 if taper or provisional <= .8 else max(.05, (1-provisional)/.2)
        weight = .5*(currents[i-1]+currents[i])*voltage/1000*efficiency*dt*factor
        cumulative += weight
        weights.append(weight)
    total = sum(weights)
    if len(currents) < 2 or total <= 0:
        raise ValueError('Insufficient current integration interval')
    accumulated = 0.0
    points = []
    for timestamp, weight in zip(times, weights):
        accumulated += weight
        points.append({'t': timestamp.isoformat(), 'soc': min(final, estimate+(final-estimate)*accumulated/total)})
    points[-1]['soc'] = final
    return {'soc_series': points, 'initial_soc_estimate': estimate, 'initial_soc_assumption': assumption,
            'final_soc': final, 'capacity_kwh': capacity, 'max_kw_observed': peak*voltage/1000,
            'taper_observed': taper, 'arrival_hour': arrival.hour+arrival.minute/60+arrival.second/3600,
            'departure_hour': departure.hour+departure.minute/60+departure.second/3600,
            'duration_hours': duration, 'soc_source': 'model-derived, not measured',
            'unrepresented_energy_kwh': max(0.0, energy-(final-estimate)*capacity),
            'energy_convention': 'Current/efficiency determine shape; normalized to recorded kWhDelivered; SoC capped at 1'}


def to_demand_samples(sessions, dataset='acn-caltech-v1'):
    if not sessions:
        return []
    earliest = min(_local(s, 'connectionTime').date() for s in sessions)
    bins = {}
    for session in sessions:
        local = _local(session, 'connectionTime')
        energy = float(session['kWhDelivered'])
        if not math.isfinite(energy) or energy < 0:
            raise ValueError('Invalid delivered energy')
        key = ((local.date()-earliest).days, local.hour)
        bins[key] = bins.get(key, 0)+energy
    return [{'dataset': dataset, 'day': d, 'hour': h, 'energy_kwh': value,
             'source': 'acn-data-caltech'} for (d, h), value in sorted(bins.items())]


def to_vehicle_sessions(sessions, capacity_lookup=battery_capacity_for):
    from sender.station_core import Vehicle
    if not sessions:
        return []
    # Replay one coherent latest day, rather than folding unrelated days together.
    latest = max(_local(s, 'connectionTime').date() for s in sessions)
    fleet, ids = [], set()
    for session in sorted(sessions, key=lambda s: _datetime(s['connectionTime'])):
        if _local(session, 'connectionTime').date() != latest:
            continue
        try:
            capacity = capacity_lookup(session.get('make'), session.get('model'), session.get('year'))
            trace = simulate_soc_trace(session, capacity)
            identifier = str(session['sessionID'])[:8]
            if identifier in ids:
                identifier = hashlib.sha256(str(session['sessionID']).encode()).hexdigest()[:8]
            target = min(trace['initial_soc_estimate']+float(session['kWhDelivered'])/capacity+.05, .95)
            if target <= trace['initial_soc_estimate']:
                continue
            vehicle = Vehicle(identifier, trace['arrival_hour'], trace['arrival_hour']+trace['duration_hours'],
                              capacity, trace['initial_soc_estimate'], target, min(trace['max_kw_observed'], 7.0))
            vehicle.soc_trace = trace  # In memory only; not added to the SQLite schema or MQTT payload.
            vehicle.data_source = 'acn-data-caltech'
            fleet.append(vehicle)
            ids.add(identifier)
            if len(fleet) == 6:
                break
        except (ValueError, TypeError, KeyError):
            continue
    return fleet


if __name__ == '__main__':
    import argparse
    from dataclasses import asdict
    parser = argparse.ArgumentParser(description='Download resumable ACN sessions into data/acn_downloads')
    parser.add_argument('--download', action='store_true', required=True)
    parser.add_argument('--days', type=int, default=42)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
    sessions = download_local(args.days, args.seconds)
    fleet = to_vehicle_sessions(sessions)
    if fleet:
        _write_json(Path(__file__).with_name('sender')/'acn_vehicles.json',
                    {'source': 'acn-data-caltech', 'vehicles': [asdict(v) for v in fleet]})
        print('Prepared sender/acn_vehicles.json with', len(fleet), 'vehicles')
