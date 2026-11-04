import unittest
from unittest.mock import patch
from station_core import Station, Vehicle, schedule
from tou_scheduler import apply_tou
from tariff import price_at, telemetry_fields


def plan_for(station):
    state = station.snapshot()
    return apply_tou(state, schedule(state, {'profile_kwh': [0.] * 24}))


class UpgradeTests(unittest.TestCase):
    def test_optimizer_error_falls_back_to_deadline_policy(self):
        s = Station([Vehicle('A', 16, 24, 40, .3, .6)])
        s.hour = 16
        with patch('tou_scheduler.milp', side_effect=RuntimeError('solver unavailable')):
            p = plan_for(s)
        self.assertEqual(p['tou_status'], 'fallback_edf')
        self.assertTrue(s.accept(p))

    def test_tariff_repeats_across_midnight(self):
        self.assertEqual(price_at(23), price_at(24))
        self.assertEqual(price_at(40), price_at(16))
        self.assertGreater(price_at(16), price_at(22))

    def test_flexible_vehicle_waits_for_night(self):
        s = Station([Vehicle('flex', 16, 24, 40, .3, .6)])
        s.hour = 16
        plan = plan_for(s)
        self.assertIn(plan['tou_status'], ('optimal', 'feasible_time_limit'))
        self.assertEqual(plan['assignments'], [])
        s.hour = 22
        self.assertGreater(sum(a['rate_kw'] for a in plan_for(s)['assignments']), 0)

    def test_deadline_overrides_expensive_price(self):
        s = Station([Vehicle('urgent', 16, 17, 10, .1, .8)])
        s.hour = 16
        p = plan_for(s)
        self.assertAlmostEqual(p['assignments'][0]['rate_kw'], 7, places=5)
        self.assertTrue(s.accept(p))

    def test_shared_socket_requires_early_charging(self):
        s = Station([Vehicle('A', 21, 23, 10, .1, .6),
                     Vehicle('B', 21, 23, 10, .1, .6)], chargers=1)
        s.hour = 21
        p = plan_for(s)
        self.assertIn(p['tou_status'], ('optimal', 'feasible_time_limit'))
        # Only 7 kWh fits in the cheap hour; 3 kWh must be delivered earlier.
        self.assertLessEqual(len(p['assignments']), 1)
        self.assertGreater(sum(a['rate_kw'] for a in p['assignments']), 0)

    def test_impossible_target_is_explicit(self):
        s = Station([Vehicle('impossible', 16, 17, 40, .1, .8)])
        s.hour = 16
        p = plan_for(s)
        self.assertEqual(p['tou_status'], 'fallback_edf')
        self.assertTrue(any('feasibility' in a for a in p['alerts']))
        self.assertTrue(s.accept(p))

    def test_future_arrival_not_assigned_now(self):
        s = Station([Vehicle('future', 22, 24, 40, .3, .6)])
        s.hour = 16
        self.assertEqual(plan_for(s)['assignments'], [])

    def test_price_fields_do_not_change_station_payload(self):
        s = Station().snapshot()
        extra = telemetry_fields(s)
        self.assertNotIn('price_per_kwh', s)
        self.assertEqual(extra['price_currency'], 'INR')
        self.assertEqual(extra['charging_load_kw'], 0)

    def test_paired_demo_meets_deadlines_and_saves_cost(self):
        from evaluate_tou import evaluate
        r = evaluate()['results']
        self.assertTrue(all(v['deadlines_met'] for v in r.values()))
        self.assertLess(r['tou']['charging_cost_inr'], r['edf']['charging_cost_inr'])
        self.assertLess(r['tou']['peak_grid_kw'], r['unmanaged']['peak_grid_kw'])
        self.assertLessEqual(r['tou']['peak_grid_kw'], 9.5 + 1e-6)
        self.assertEqual(r['tou']['fallback_cycles'], 0)
