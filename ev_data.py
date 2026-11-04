
import json
import sys
import random
from pathlib import Path

SESSIONS_PATH = Path(__file__).with_name("acn_sessions.json")
# SESSIONS_PATH = Path(__file__).with_name("acn_sessions_w.json")

# Choose: "fallback_synthetic" or "controlled_random_fallback"
# FALLBACK_MODE = "controlled_random_fallback"
FALLBACK_MODE = "fallback_synthetic"

# Controlled random generation settings
RANDOM_SEED = 42
RANDOM_EV_COUNT = 4

RANDOM_RANGES = {
    "capacity_kwh": (30.0, 100.0),
    "soc_percent": (10.0, 70.0),
    "target_soc_percent": (70.0, 100.0),
    "hours_remaining": (1.0, 8.0),
    "max_power_kw": (3.0, 11.0),
}

_FALLBACK_EVS = {
    "C1": {
        "capacity_kwh": 60.0,
        "soc_percent": 30.0,
        "target_soc_percent": 80.0,
        "hours_remaining": 4.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
    "C2": {
        "capacity_kwh": 40.0,
        "soc_percent": 50.0,
        "target_soc_percent": 90.0,
        "hours_remaining": 2.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
    "C3": {
        "capacity_kwh": 75.0,
        "soc_percent": 20.0,
        "target_soc_percent": 70.0,
        "hours_remaining": 6.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
    "C4": {
        "capacity_kwh": 30.0,
        "soc_percent": 60.0,
        "target_soc_percent": 95.0,
        "hours_remaining": 1.0,
        "max_power_kw": 7.0,
        "transition_soc": 0.80,
    },
}

EVS = {cid: ev.copy() for cid, ev in _FALLBACK_EVS.items()}
SESSION_META: dict = {}
SESSION_SOURCE: str = "fallback_synthetic"


def generate_controlled_random_evs() -> dict:
    """Generate reproducible EV profiles within configured ranges."""
    rng = random.Random(RANDOM_SEED)
    generated = {}

    for i in range(1, RANDOM_EV_COUNT + 1):
        cid = f"C{i}"

        capacity = round(
            rng.uniform(*RANDOM_RANGES["capacity_kwh"]), 1
        )
        initial_soc = round(
            rng.uniform(*RANDOM_RANGES["soc_percent"]), 1
        )

        # Ensure the target SOC is greater than the initial SOC.
        min_target = max(
            RANDOM_RANGES["target_soc_percent"][0],
            initial_soc + 5.0,
        )
        max_target = RANDOM_RANGES["target_soc_percent"][1]

        if min_target > max_target:
            min_target = max_target

        target_soc = round(
            rng.uniform(min_target, max_target), 1
        )

        generated[cid] = {
            "capacity_kwh": capacity,
            "soc_percent": initial_soc,
            "target_soc_percent": target_soc,
            "hours_remaining": round(
                rng.uniform(*RANDOM_RANGES["hours_remaining"]), 1
            ),
            "max_power_kw": round(
                rng.uniform(*RANDOM_RANGES["max_power_kw"]), 1
            ),
            "transition_soc": 0.80,
        }

    return generated


def apply_fallback() -> None:
    """Apply the selected fallback profile source."""
    global EVS, SESSION_META, SESSION_SOURCE

    SESSION_META = {}

    if FALLBACK_MODE == "controlled_random_fallback":
        EVS = generate_controlled_random_evs()
        SESSION_SOURCE = "controlled_random_fallback"
        print(
            f"[ev_data] Generated {len(EVS)} controlled random EV profiles "
            f"(seed={RANDOM_SEED}).",
            file=sys.stderr,
        )

    elif FALLBACK_MODE == "fallback_synthetic":
        EVS = {
            cid: ev.copy()
            for cid, ev in _FALLBACK_EVS.items()
        }
        SESSION_SOURCE = "fallback_synthetic"
        print(
            "[ev_data] Using hard-coded synthetic EV profiles.",
            file=sys.stderr,
        )

    else:
        raise ValueError(
            f"Unsupported FALLBACK_MODE: {FALLBACK_MODE!r}. "
            "Choose 'fallback_synthetic' or "
            "'controlled_random_fallback'."
        )


def load_sessions() -> None:
    global EVS, SESSION_META, SESSION_SOURCE

    if not SESSIONS_PATH.exists():
        print(
            f"[ev_data] WARNING: {SESSIONS_PATH.name} not found.",
            file=sys.stderr,
        )
        apply_fallback()
        return

    try:
        data = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"[ev_data] ERROR reading {SESSIONS_PATH.name}: {e}",
            file=sys.stderr,
        )
        apply_fallback()
        return

    new_evs = {}
    new_meta = {}

    for session in data.get("sessions", []):
        cfg = session.get("_gridsense_config")
        if not isinstance(cfg, dict):
            continue

        cid = cfg.get("charger_id")
        if not cid:
            continue

        try:
            ev = {
                "capacity_kwh": float(cfg["capacity_kwh"]),
                "soc_percent": float(cfg["initial_soc_percent"]),
                "target_soc_percent": float(
                    cfg["target_soc_percent"]
                ),
                "hours_remaining": float(cfg["hours_remaining"]),
                "max_power_kw": float(cfg.get("max_power_kw", 7.0)),
                "transition_soc": float(
                    cfg.get("transition_soc", 0.80)
                ),
            }

            if (
                ev["capacity_kwh"] <= 0
                or not 0 <= ev["soc_percent"] <= 100
                or not 0 <= ev["target_soc_percent"] <= 100
                or ev["target_soc_percent"] < ev["soc_percent"]
                or ev["hours_remaining"] <= 0
                or ev["max_power_kw"] <= 0
            ):
                continue

        except (KeyError, TypeError, ValueError):
            continue

        new_evs[cid] = ev
        new_meta[cid] = session

    if new_evs:
        EVS = new_evs
        SESSION_META = new_meta

        meta = data.get("_metadata", {})
        SESSION_SOURCE = meta.get("source", "acn_sessions.json")

        print(
            f"[ev_data] Loaded {len(EVS)} sessions "
            f"from {SESSIONS_PATH.name}"
        )
        print(f"[ev_data] Source: {SESSION_SOURCE}")
    else:
        print(
            f"[ev_data] WARNING: no valid sessions in "
            f"{SESSIONS_PATH.name}.",
            file=sys.stderr,
        )
        apply_fallback()


load_sessions()


if __name__ == "__main__":
    print(f"SESSION_SOURCE = {SESSION_SOURCE}")
    print(f"Chargers: {list(EVS.keys())}")

    for cid, ev in EVS.items():
        print(f"  {cid}: {ev}")

    print("\nSession metadata (provenance):")
    for cid, meta in SESSION_META.items():
        print(
            f"  {cid}: sessionID={meta.get('sessionID')}, "
            f"site={meta.get('site')}, "
            f"kWhDelivered={meta.get('kWhDelivered')}"
        )

