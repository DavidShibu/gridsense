import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import acn_data
from sender import station_core
from sender.simulator import history_payload


def fixture_session(day=0, hour=8, energy=10, identifier=None, currents=None):
    start = datetime(2020, 1, 1, hour, tzinfo=timezone(timedelta(hours=-8)))+timedelta(days=day)
    values = currents or [24, 24, 24, 24, 24, 24]
    return {'sessionID': identifier or f'sess{day:04d}{hour:02d}', 'timezone': 'America/Los_Angeles',
            'connectionTime': start.isoformat(), 'disconnectTime': (start+timedelta(hours=2)).isoformat(),
            'kWhDelivered': energy, 'chargingCurrent': {'current': values, 'timestamps':
            [(start+timedelta(hours=2*i/(len(values)-1))).isoformat() for i in range(len(values))]},
            'userInputs': []}


class AcnDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = patch.object(acn_data, 'CACHE_PATH', Path(self.tmp.name)/'cache.json')
        self.local = patch.object(acn_data, 'LOCAL_DIR', Path(self.tmp.name)/'downloads')
        self.local.start()
        self.addCleanup(self.local.stop)
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch('requests.get', side_effect=AssertionError('Network is forbidden in unit tests'))
        self.network.start()
        self.addCleanup(self.network.stop)
        acn_data.battery_capacity_for.cache_clear()
        acn_data._ev_catalog.cache_clear()

    def test_saved_partial_days_are_live_only(self):
        session = fixture_session()
        acn_data._write_json(acn_data.LOCAL_DIR/'caltech-2020-01-01.json',
                             {'site': 'caltech', 'day': '2020-01-01', 'complete': False,
                              'sessions': [session]})
        self.assertEqual(acn_data.saved_sessions(), [session])
        with self.assertRaises(acn_data.AcnDataError):
            acn_data.saved_sessions(for_history=True)
        with patch.object(acn_data, 'fetch_sessions', side_effect=AssertionError('no network')):
            self.assertEqual(history_payload()['source'], 'synthetic-fallback')
            self.assertEqual(station_core.real_or_synthetic_vehicles()[0].data_source, 'acn-data-caltech')

    def test_saved_history_requires_contiguous_complete_days(self):
        for day in range(18):
            session = fixture_session(day)
            date = acn_data._local(session, 'connectionTime').date().isoformat()
            acn_data._write_json(acn_data.LOCAL_DIR/f'caltech-{date}.json',
                                 {'site': 'caltech', 'day': date, 'complete': True, 'sessions': [session]})
        self.assertEqual(len(acn_data.saved_sessions(for_history=True)), 18)
        (acn_data.LOCAL_DIR/'caltech-2020-01-09.json').unlink()
        with self.assertRaises(acn_data.AcnDataError):
            acn_data.saved_sessions(for_history=True)

    def test_download_keeps_and_resumes_partial_page_progress(self):
        start = datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=-8)))
        first = Mock()
        first.json.return_value = {'_items': [fixture_session()], '_links': {'next': {}}}
        second = Mock()
        second.json.return_value = {'_items': [fixture_session(hour=9)], '_links': {}}
        with patch.dict(os.environ, {'ACN_DATA_TOKEN': 'secret'}), patch.object(
                acn_data, 'recent_window', return_value=(start, start+timedelta(days=1))):
            with patch.object(acn_data, '_get', side_effect=[first, OSError('secret')]):
                self.assertEqual(len(acn_data.download_local(days=1)), 1)
            with patch.object(acn_data, '_get', return_value=second) as get:
                self.assertEqual(len(acn_data.download_local(days=1)), 2)
                self.assertEqual(get.call_args.kwargs['params']['page'], 2)
        record = json.loads((acn_data.LOCAL_DIR/'caltech-2020-01-01.json').read_text())
        self.assertTrue(record['complete'])
        self.assertNotIn('secret', json.dumps(record))

    def test_fetch_sessions_returns_real_sessions_when_token_set(self):
        sessions = [fixture_session(), fixture_session(1, 9)]
        with patch.dict(os.environ, {'ACN_DATA_TOKEN':'private-test-token'}), patch(
                'acnportal.acndata.DataClient.get_sessions', return_value=iter(sessions)) as get:
            result = acn_data.fetch_sessions(start='2020-01-01', end='2020-01-04')
        rows = acn_data.to_demand_samples(result)
        self.assertEqual([(r['day'], r['hour']) for r in rows], [(0,8), (1,9)])
        self.assertTrue(all(r['source']=='acn-data-caltech' for r in rows))
        self.assertTrue(get.call_args.kwargs['timeseries'])
        self.assertIn('Wed, 01 Jan 2020 00:00:00 GMT', get.call_args.kwargs['cond'])
        self.assertNotIn('private-test-token', acn_data.CACHE_PATH.read_text())

    def test_fetch_sessions_raises_when_token_missing(self):
        with self.assertRaises(acn_data.AcnDataNotConfigured):
            acn_data.fetch_sessions(start='2020-01-01', end='2020-01-04')

    def test_simulate_soc_trace_matches_delivered_energy(self):
        trace = acn_data.simulate_soc_trace(fixture_session(), 40, initial_soc=.3)
        self.assertAlmostEqual(trace['final_soc'], .55, delta=.01)
        self.assertEqual(len(trace['soc_series']), 6)
        self.assertAlmostEqual(trace['soc_series'][0]['soc'], .3)
        self.assertEqual(trace['soc_series'][-1]['soc'], trace['final_soc'])
        self.assertTrue(all(a['soc']<=b['soc'] for a,b in zip(trace['soc_series'],trace['soc_series'][1:])))

    def test_taper_detected_above_80_percent(self):
        trace = acn_data.simulate_soc_trace(fixture_session(energy=6, currents=[32]*8+[8,4]), 40, initial_soc=.8)
        self.assertTrue(trace['taper_observed'])
        self.assertAlmostEqual(trace['initial_soc_estimate'], .8)
        self.assertLessEqual(trace['final_soc'], 1)

    def test_requested_energy_and_overnight_session(self):
        session = fixture_session(hour=23)
        session['userInputs'] = [{'kWhRequested': 20}]
        trace = acn_data.simulate_soc_trace(session, 40)
        self.assertAlmostEqual(trace['initial_soc_estimate'], .5)
        self.assertEqual(trace['arrival_hour'], 23)
        self.assertEqual(trace['departure_hour'], 1)
        vehicle = acn_data.to_vehicle_sessions([session], lambda *args: 40)[0]
        self.assertEqual(vehicle.departure, 25)

    def test_real_or_synthetic_history_falls_back_cleanly(self):
        with patch.object(acn_data, 'recent_window', return_value=('2020-01-01','2020-02-12')), patch.object(
                acn_data, 'fetch_sessions', side_effect=OSError('must-not-log-secret')), self.assertLogs(level='WARNING') as captured:
            rows = station_core.real_or_synthetic_history(42)
        self.assertEqual(rows, station_core.historical_sessions(42, seed=42))
        self.assertIn('[FALLBACK] Using synthetic history', '\n'.join(captured.output))
        self.assertNotIn('must-not-log-secret', '\n'.join(captured.output))

    def test_no_token_history_payload_is_explicit_fallback(self):
        payload = history_payload()
        self.assertEqual(payload['source'], 'synthetic-fallback')
        self.assertEqual(len(payload['samples']), 1008)

    def test_insufficient_days_fall_back(self):
        with patch.object(acn_data, 'recent_window', return_value=('2020-01-01','2020-02-12')), patch.object(
                acn_data, 'fetch_sessions', return_value=[fixture_session()]):
            self.assertEqual(station_core.real_or_synthetic_history(42), station_core.historical_sessions(42))

    def test_real_history_is_dense_without_inventing_energy(self):
        sessions = [fixture_session(day=d) for d in range(18)]
        with patch.object(acn_data, 'recent_window', return_value=('2020-01-01','2020-02-12')), patch.object(
                acn_data, 'fetch_sessions', return_value=sessions), patch.object(acn_data, 'to_vehicle_sessions', return_value=[]):
            payload = history_payload()
        self.assertEqual(payload['dataset'], 'acn-caltech-v1')
        self.assertEqual(payload['source'], 'acn-data-caltech')
        self.assertEqual(len(payload['samples']), 18*24)
        self.assertEqual(sum(r['energy_kwh'] for r in payload['samples']), 180)

    def test_synthetic_only_makes_no_fetches(self):
        with patch.object(acn_data, 'fetch_sessions', side_effect=AssertionError('should not fetch')):
            self.assertEqual(history_payload(True)['source'], 'synthetic-fallback')
            self.assertEqual(station_core.real_or_synthetic_vehicles(False), station_core.demo_vehicles())

    def test_cache_ttl_and_minimum_energy_filter(self):
        with patch.dict(os.environ, {'ACN_DATA_TOKEN':'secret'}), patch('acnportal.acndata.DataClient.get_sessions',
                side_effect=lambda *a, **k: iter([fixture_session(energy=1)])) as get:
            with patch('acn_data.time.time', return_value=100):
                self.assertEqual(len(acn_data.fetch_sessions(start='2020-01-01',end='2020-01-03')), 1)
            with patch('acn_data.time.time', return_value=200):
                self.assertEqual(acn_data.fetch_sessions(start='2020-01-01',end='2020-01-03',min_kwh=2), [])
            self.assertEqual(get.call_count, 1)
            with patch('acn_data.time.time', return_value=100+acn_data.CACHE_TTL+1):
                acn_data.fetch_sessions(start='2020-01-01',end='2020-01-03')
            self.assertEqual(get.call_count, 2)

    def test_capacity_lookup_and_unknown_default(self):
        with patch.object(acn_data, '_ev_catalog', return_value=[{'brand':'Example', 'model':'EV', 'year':2020,
                      'battery':{'pack_capacity_kwh_net':58}}]) as catalog:
            self.assertEqual(acn_data.battery_capacity_for('Example','EV',2020), 58)
            self.assertEqual(acn_data.battery_capacity_for('Example','EV',2020), 58)
            self.assertEqual(catalog.call_count, 1)
        with self.assertLogs(level='WARNING'):
            self.assertEqual(acn_data.battery_capacity_for(None,None,None), 40)

    def test_fleet_caps_six_and_disambiguates_ids(self):
        sessions = [fixture_session(identifier=f'samehead{i}') for i in range(8)]
        fleet = acn_data.to_vehicle_sessions(sessions, lambda *args: 40)
        self.assertEqual(len(fleet), 6)
        self.assertEqual(len({v.id for v in fleet}), 6)
        self.assertTrue(all(0<v.max_kw<=7 and v.departure>v.arrival for v in fleet))

    def test_latest_available_window_excludes_partial_day(self):
        response = Mock()
        response.json.return_value = {'_items':[fixture_session(day=41)]}
        with patch.dict(os.environ, {'ACN_DATA_TOKEN':'secret'}), patch.object(acn_data, '_get', return_value=response):
            start, end = acn_data.recent_window(42)
        self.assertEqual(end.hour, 0)
        self.assertEqual((end-start).days, 42)

    def test_end_date_override_is_site_local(self):
        with patch.dict(os.environ, {'ACN_DATA_TOKEN': 'test', 'ACN_DATA_END': '2020-02-12'}):
            start, end = acn_data.recent_window(42)
        self.assertEqual(end.isoformat(), '2020-02-12T00:00:00-08:00')
        self.assertEqual((end-start).days, 42)

    def test_logger_padding_is_trimmed_to_connected_interval(self):
        session = fixture_session()
        series = session['chargingCurrent']
        series['timestamps'].insert(0, (acn_data._datetime(session['connectionTime'])-timedelta(minutes=1)).isoformat())
        series['timestamps'].append((acn_data._datetime(session['disconnectTime'])+timedelta(minutes=1)).isoformat())
        series['current'] = [0]+series['current']+[0]
        trace = acn_data.simulate_soc_trace(session, 40)
        self.assertEqual(len(trace['soc_series']), 6)
        self.assertAlmostEqual(trace['final_soc'], .55)

    def test_invalid_trace_rejected(self):
        session = fixture_session()
        session['chargingCurrent']['timestamps'][2] = session['chargingCurrent']['timestamps'][1]
        with self.assertRaises(ValueError):
            acn_data.simulate_soc_trace(session, 40)

    def test_health_reports_latest_replayed_source(self):
        from station_store import ingest, database
        from station_service import Handler
        db = Path(self.tmp.name)/'health.db'
        handler = Handler.__new__(Handler)
        handler.path = '/health'
        handler.respond = Mock()
        with patch('station_service.database', side_effect=lambda: database(db)):
            for source in ('acn-data-caltech', 'synthetic-fallback', 'acn-data-caltech'):
                ingest({'kind':'history','dataset':source,'source':source,
                        'samples':[{'day':0,'hour':0,'energy_kwh':10}]}, db)
                handler.do_GET()
                self.assertEqual(handler.respond.call_args.args[0]['data_source'], source)

    def test_cache_can_be_unwritable_without_losing_real_results(self):
        with patch.dict(os.environ, {'ACN_DATA_TOKEN':'secret'}), patch(
                'acnportal.acndata.DataClient.get_sessions', return_value=iter([fixture_session()])), patch(
                'pathlib.Path.write_text', side_effect=OSError('denied')):
            result = acn_data.fetch_sessions(start='2020-01-01',end='2020-01-03')
        self.assertEqual(len(result), 1)

    def test_shorter_history_replay_does_not_mix_old_days(self):
        from station_store import ingest, database
        db = Path(self.tmp.name)/'replace.db'
        payload = {'kind':'history','dataset':'acn-caltech-v1','source':'acn-data-caltech',
                   'samples':[{'day':d,'hour':0,'energy_kwh':10} for d in range(3)]}
        ingest(payload, db)
        payload['samples'] = payload['samples'][:1]
        ingest(payload, db)
        with database(db) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM demand_samples').fetchone()[0], 1)
