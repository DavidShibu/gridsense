"""Illustrative tariff in INR/kWh; hours are absolute SIMULATION hours."""
import math

HOURLY_PRICES = (3.,) * 6 + (6.,) * 10 + (12.,) * 6 + (3.,) * 2


def price_at(hour):
    if not math.isfinite(hour):
        raise ValueError('Simulation hour must be finite')
    return HOURLY_PRICES[math.floor(hour) % 24]


def telemetry_fields(state):
    active = [e for e in state['vehicles'] if e['arrival'] <= state['hour'] < e['departure']
              and e['remaining_kwh'] > 1e-8]
    # Demand envelope only: not a separate counterfactual simulation.
    demand = sum(sorted((e['max_kw'] for e in active), reverse=True)[:len(state['chargers'])])
    return {'price_per_kwh': price_at(state['hour']), 'price_currency': 'INR',
            'charging_load_kw': max(0., state['load_kw'] - state['base_kw']),
            'unmanaged_demand_estimate_kw': state['base_kw'] + demand}
