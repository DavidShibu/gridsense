"""
Optional ACN-Data live client.

If you have a Caltech ACN-Data API token (request one at
https://ev.caltech.edu/), set it as an environment variable:

    export ACN_DATA_TOKEN="your_token_here"

and run:

    uv run python acndata_client.py

This will fetch fresh sessions from the Caltech site and update
acn_sessions.json with real session records. The simulator will then
use those records on its next start.

If no token is set, this script is a no-op.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "acn_sessions.json"


def fetch_live_sessions(site: str = "caltech", max_sessions: int = 4) -> list:
    token = os.environ.get("ACN_DATA_TOKEN")
    if not token:
        print("[acndata] ACN_DATA_TOKEN env var not set - skipping live fetch.")
        return []

    try:
        from acnportal.acndata import DataClient  # type: ignore
    except ImportError:
        print("[acndata] acnportal not installed. Install with: uv add acnportal")
        return []

    print(f"[acndata] Connecting to ACN-Data as site={site}...")
    client = DataClient(api_token=token)

    try:
        sessions_iter = client.get_sessions(site, timeseries=False)
        sessions = []
        for i, s in enumerate(sessions_iter):
            if i >= max_sessions * 3:
                break
            sessions.append(s)
    except Exception as e:
        print(f"[acndata] API error: {e}")
        return []

    print(f"[acndata] Fetched {len(sessions)} candidate sessions.")
    return sessions


def normalize_session(raw: dict, charger_id: str) -> dict:
    user_inputs = raw.get("userInputs", {}) or {}
    minutes = user_inputs.get("minutesAvailable") or 0

    estimated = {
        "capacity_kwh": 50.0,
        "initial_soc_percent": 35.0,
        "target_soc_percent": 85.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    }
    hours = max(0.5, minutes / 60.0) if minutes else 4.0

    return {
        "sessionID": raw.get("sessionID", f"live_{charger_id}"),
        "site": raw.get("site", "caltech"),
        "spaceID": raw.get("spaceID", charger_id),
        "stationID": raw.get("stationID", "unknown"),
        "connectionTime": raw.get("connectionTime"),
        "disconnectTime": raw.get("disconnectTime"),
        "kWhDelivered": raw.get("kWhDelivered", 0.0),
        "userInputs": user_inputs,
        "_gridsense_config": {
            "charger_id": charger_id,
            **estimated,
            "hours_remaining": hours,
        },
        "estimated_fields": [
            "capacity_kwh", "initial_soc_percent", "target_soc_percent",
        ],
        "estimation_note": "Live session from ACN-Data; battery params are configured estimates.",
    }


def main() -> int:
    print(f"[acndata] Backend: ACN-Data live client")
    print(f"[acndata] Token present: {'yes' if os.environ.get('ACN_DATA_TOKEN') else 'no'}")
    print()

    sessions = fetch_live_sessions()
    if not sessions:
        print("[acndata] No live sessions available. Keeping cached acn_sessions.json.")
        return 0

    picked = []
    for s in sessions:
        ui = s.get("userInputs") or {}
        if ui.get("minutesAvailable"):
            picked.append(s)
        if len(picked) >= 4:
            break

    if len(picked) < 4:
        print(f"[acndata] Only {len(picked)} usable sessions found (need 4). Aborting update.")
        return 1

    normalized = [
        normalize_session(s, cid)
        for s, cid in zip(picked, ["C1", "C2", "C3", "C4"])
    ]

    output = {
        "_metadata": {
            "source": "Caltech ACN-Data (https://ev.caltech.edu/) - LIVE FETCH",
            "schema_reference": "https://acnportal.readthedocs.io/en/latest/acndata/data_client.html",
            "description": "Live-fetched sessions from ACN-Data API.",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "site": "caltech",
            "session_count": len(normalized),
        },
        "sessions": normalized,
    }

    backup = DB_PATH.with_suffix(".json.bak")
    if DB_PATH.exists():
        DB_PATH.rename(backup)
        print(f"[acndata] Backed up old sample to {backup.name}")

    DB_PATH.write_text(json.dumps(output, indent=2))
    print(f"[acndata] Wrote {len(normalized)} live sessions to {DB_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())