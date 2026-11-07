import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from sender.station_core import Station, Vehicle, schedule, demand_model
from station_service import process


class StationTests(unittest.TestCase):
    def test_full_day_constraints_and_departures(self):
        s = Station()
        queued = False
        for _ in range(190):
            state = s.snapshot()
            queued |= any(v["status"] == "queued" and v["arrival"] > 0 for v in state["vehicles"])
            plan = schedule(state)
            self.assertLessEqual(sum(a["rate_kw"] for a in plan["assignments"]), 9)
            self.assertLessEqual(len(plan["assignments"]), 2)
            self.assertTrue(s.accept(plan))
            s.step(1/30)
            self.assertLessEqual(s.snapshot()["load_kw"], 10 + 1e-8)
            for ev in s.vehicles:
                self.assertLessEqual(ev.soc, ev.target + 1e-8)
                if s.hour >= ev.departure:
                    self.assertEqual(ev.power_kw, 0)
                    self.assertEqual(ev.status, "departed")
        self.assertTrue(queued)
        self.assertTrue(any("departed" in a for a in schedule(s.snapshot())["alerts"]))

    def test_atomic_rejection_and_duplicate(self):
        s = Station()
        plan = schedule(s.snapshot())
        bad = json.loads(json.dumps(plan))
        bad["assignments"][0]["rate_kw"] = float("nan")
        self.assertFalse(s.accept(bad))
        self.assertEqual(s.command, {})
        self.assertTrue(s.accept(plan))
        self.assertFalse(s.accept(plan))

    def test_watchdog_and_capacity_drop(self):
        s = Station()
        s.accept(schedule(s.snapshot()))
        s.capacity_kw = 2
        s.step(.05)
        self.assertLessEqual(s.snapshot()["load_kw"], 2 + 1e-8)
        s.step(.1)
        energy = sum(e.delivered_kwh for e in s.vehicles)
        s.step(.1)
        self.assertEqual(energy, sum(e.delivered_kwh for e in s.vehicles))

    def test_no_early_arrivals(self):
        s = Station([Vehicle("future", 1, 2, 10, .5, .6)])
        self.assertEqual(schedule(s.snapshot())["assignments"], [])

    def test_forecast_evaluation(self):
        model = demand_model()
        self.assertEqual(len(model["profile_kwh"]), 24)
        self.assertLess(model["mae_kwh"], model["baseline_mae_kwh"])

    def test_persistence_and_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"station.db"
            state = Station().snapshot()
            state["run_id"] = "test"
            process(state, db)
            process(state, db)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM cycles").fetchone()[0], 1)
                row = conn.execute("SELECT telemetry,decision FROM cycles").fetchone()
            self.assertEqual(json.loads(row[0])["source"], "synthetic-fallback")
            self.assertIn("assignments", json.loads(row[1]))


if __name__ == "__main__":
    unittest.main()
