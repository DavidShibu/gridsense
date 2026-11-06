import json
import tempfile
import unittest
from pathlib import Path
from station_core import Station
from station_store import ingest, database, read_state
from decision_engine import stabilize, decide
from simulator import history_payload


class RubricTests(unittest.TestCase):
    def test_independent_dashboard_path_and_topics(self):
        nodes = json.loads((Path(__file__).parents[1]/'node-red/flows.json').read_text())
        nodes = {n['id']:n for n in nodes}
        self.assertEqual(nodes['sensor']['topic'],'ev/telemetry')
        self.assertEqual(set(nodes['sensor']['wires'][0]),{'live-filter','request'})
        self.assertEqual(nodes['actuator']['topic'],'ev/actuator')
        self.assertTrue({'live-dashboard', 'soc-router', 'load-series', 'price-history'} <= set(nodes['live-filter']['wires'][0]))

    def test_db_ingest_idempotent_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'test.db'
            ingest(history_payload(),db)
            ingest(history_payload(),db)
            with database(db) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM demand_samples').fetchone()[0],1008)

    def test_complete_reference_architecture_wiring(self):
        nodes = {n['id']: n for n in json.loads(
            (Path(__file__).parents[1]/'node-red/flows.json').read_text())}
        # Storage must precede analytics; only the decision path drives MQTT output.
        for source, target in [('request', 'analytics'), ('analytics', 'stored'),
                               ('stored', 'db-decision'), ('db-decision', 'route'),
                               ('command', 'actuator')]:
            self.assertEqual(nodes[source]['wires'], [[target]])
        self.assertEqual(nodes['route']['wires'][1], ['command'])
        self.assertTrue(nodes['analytics']['url'].endswith('/store'))
        self.assertTrue(nodes['db-decision']['url'].endswith('/decide'))
        self.assertEqual(nodes['actuator']['type'], 'mqtt out')
        self.assertEqual(nodes['ack']['topic'], 'ev/ack')
        self.assertIn('ack-store', nodes['ack']['wires'][0])
        self.assertTrue(nodes['ack-store']['url'].endswith('/ack'))
        for name in ('sensor', 'actuator', 'ack'):
            self.assertEqual(nodes[name]['broker'], 'broker')

    def test_unstored_state_cannot_drive_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'test.db'
            with self.assertRaises(ValueError):
                read_state({'run_id':'absent','sequence':1},db)

    def test_dwell_prevents_unnecessary_reassignment(self):
        s = Station()
        state = s.snapshot()
        state['hour'] = .05
        previous = {'assignments':[{'ev_id':'EV1','charger_id':'C1','rate_kw':4}], 'assigned_since':{'EV1':0}}
        plan = {'assignments':[{'ev_id':'EV2','charger_id':'C1','rate_kw':7}], 'forecast_factor':1}
        state['chargers'] = ['C1']
        result = stabilize(state,plan,previous)
        self.assertEqual(result['assignments'][0]['ev_id'],'EV1')
        state['hour'] = .2
        plan['assignments'] = [{'ev_id':'EV2','charger_id':'C1','rate_kw':7}]
        self.assertEqual(stabilize(state,plan,previous)['assignments'][0]['ev_id'],'EV2')

    def test_safety_overrides_deadband(self):
        s = Station()
        state = s.snapshot()
        state.update(capacity_kw=1.2, hour=.01)
        previous = {'assignments':[{'ev_id':'EV1','charger_id':'C1','rate_kw':4}], 'assigned_since':{'EV1':0}}
        plan = {'assignments':previous['assignments'],'forecast_factor':1}
        result = stabilize(state,plan,previous)
        self.assertLessEqual(sum(a['rate_kw'] for a in result['assignments']),.2)

    def test_untrained_decision_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'test.db'
            state = Station().snapshot()
            state.update(run_id='test',timestamp=1)
            key = ingest(state,db)
            decision = decide(key,db,Path(tmp)/'absent.pkl')['decision']
            self.assertEqual(decision['model'],'untrained_safe_rules')
            self.assertEqual(decision['sensor_timestamp'],1)

    def test_models_train_only_from_database_and_report_all_categories(self):
        from ml_train import train
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'test.db'
            with self.assertRaises(ValueError):
                train(db,Path(tmp)/'artifacts')
            ingest(history_payload(),db)
            report=train(db,Path(tmp)/'artifacts')
            self.assertEqual(len(report['models']),5)
            self.assertIn('traditional_svr', report['models'])
            self.assertIn('ensemble_xgboost', report['models'])
            eligible = [name for name, m in report['models'].items()
                        if m['computational']['inference_p95_ms'] <= 100
                        and m['validation']['rmse_kwh'] <= report['baseline_validation']['rmse_kwh']]
            expected = min(eligible, key=lambda name: report['models'][name]['validation']['rmse_kwh']) if eligible else 'constant_baseline'
            self.assertEqual(report['selected_model'], expected)
            self.assertLess(max(report['training_days']),min(report['validation_days']))
            self.assertLess(max(report['validation_days']),min(report['test_days']))
            for model in report['models'].values():
                self.assertTrue({'accuracy','precision','recall','f1','rmse_kwh','mae_kwh','r2'} <= model['test'].keys())
                self.assertGreater(model['computational']['model_size_bytes'],0)
