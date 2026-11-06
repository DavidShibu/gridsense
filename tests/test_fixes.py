import json
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from sender.station_core import Station, schedule
from decision_engine import stabilize, load_bundle, _cache
from ml_train import scores


class FixTests(unittest.TestCase):
    def test_identical_binary_scores_are_valid_for_different_forecasts(self):
        y=np.array([10.,20.,40.,50.])
        a=scores(y,np.array([11.,21.,39.,49.]))
        b=scores(y,np.array([15.,25.,35.,45.]))
        self.assertEqual(a['f1'],b['f1'])
        self.assertNotEqual(a['rmse_kwh'],b['rmse_kwh'])

    def test_cache_never_reloads_changed_artifact_during_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bundle.pkl'
            path.write_bytes(pickle.dumps({'model':None,'baseline':1,'report':{}}))
            original_read=Path.read_bytes
            with patch.object(Path,'read_bytes',autospec=True,side_effect=original_read) as reader:
                first=load_bundle(path)
                path.write_bytes(pickle.dumps({'model':None,'baseline':2,'report':{}}))
                self.assertIs(load_bundle(path),first)
                self.assertEqual(reader.call_count,1)
            _cache.pop(str(path.resolve()))

    def test_edf_feasible_requests_precede_impossible_ones(self):
        state=Station().snapshot()
        plan=schedule(state)
        self.assertEqual(plan['assignments'][0]['ev_id'],'EV1')
        self.assertEqual(plan['assignments'][0]['rate_kw'],7)

    def test_full_congested_run_meets_deadlines_and_margin(self):
        s=Station(); previous=None; switches={}; mapping={}; rapid=0
        for _ in range(185):
            state=s.snapshot()
            plan=stabilize(state,schedule(state),previous)
            self.assertLessEqual(sum(a['rate_kw'] for a in plan['assignments']),8.5+1e-8)
            self.assertTrue(s.accept(plan))
            current={a['charger_id']:a['ev_id'] for a in plan['assignments'] if a['rate_kw']>0}
            for c in s.chargers:
                if mapping.get(c)!=current.get(c):
                    if c in switches and s.hour-switches[c]<.1-1e-8:
                        rapid+=1
                    switches[c]=s.hour
            mapping=current; previous=plan
            s.step(1/30)
            self.assertLessEqual(s.snapshot()['load_kw'],9.5+1e-8)
        self.assertGreater(sum(e.remaining<=.01 for e in s.vehicles),0)
        self.assertEqual(rapid,0)

    def test_actuator_rejects_plan_above_reserved_limit(self):
        s=Station()
        plan=schedule(s.snapshot())
        plan['assignments'][0]['rate_kw']=7
        plan['assignments'][1]['rate_kw']=2
        self.assertFalse(s.accept(plan))

    def test_deadband_holds_rate_without_later_redistribution(self):
        s=Station(); state=s.snapshot()
        state['chargers']=['C1']
        previous={'assignments':[{'ev_id':'EV1','charger_id':'C1','rate_kw':6.9}],'assigned_since':{'EV1':0}}
        plan={'assignments':previous['assignments'],'forecast_factor':1}
        self.assertEqual(stabilize(state,plan,previous)['assignments'][0]['rate_kw'],6.9)
