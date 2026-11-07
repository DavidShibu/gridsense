"""Integration-test-only ACN fixtures. Never included in the demo submission."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acn_data
from sender.simulator import main
from test_acn_data import fixture_session

if __name__ == '__main__':
    sessions = [fixture_session(day=d, hour=h, energy=value)
                for d in range(42) for h, value in ((8,60+d%7),(18,10+d%4))]
    with patch.object(acn_data, 'recent_window', return_value=('2020-01-01','2020-02-12')), patch.object(
            acn_data, 'fetch_sessions', return_value=sessions):
        if '--history' in sys.argv:
            # Do not export test fixtures as a real user's prepared fleet.
            with patch.object(acn_data, 'to_vehicle_sessions', return_value=[]):
                main()
        else:
            main()
