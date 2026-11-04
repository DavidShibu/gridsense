"""
GridSense Battery Model - ACN-Sim Linear2StageBattery integration

This module provides a real EV battery model based on the ACN-Sim
project from Caltech (https://github.com/zach401/acnportal,
documentation: https://acnportal.readthedocs.io/en/latest/acnsim/models.html).

The Linear2StageBattery models the two-stage charging behavior that
real lithium-ion EV batteries exhibit:
  - Stage 1 (SOC < transition_soc): Constant Current (CC) - the battery
    accepts the full requested charging power.
  - Stage 2 (SOC >= transition_soc): Linear taper - the effective charging
    power decreases linearly from max_power at transition_soc to 0 at 100% SOC.

If `acnportal` is installed in the environment, this module imports the
real `acnportal.acnsim.Linear2StageBattery` and wraps it. Otherwise it
uses a faithful local implementation of the same algorithm.
"""

from __future__ import annotations
from typing import Optional

_ACNSIM_AVAILABLE = False
_ACNSIM_VERSION: Optional[str] = None
try:
    import acnportal  # type: ignore
    _ACNSIM_VERSION = getattr(acnportal, "__version__", "unknown")
    _ACNSIM_AVAILABLE = True
except ImportError:
    pass


def battery_backend() -> str:
    """Return a string identifying which battery backend is in use."""
    if _ACNSIM_AVAILABLE:
        return f"acnportal.acnsim.Linear2StageBattery (v{_ACNSIM_VERSION})"
    return "Linear2StageBattery (local impl, acnportal not installed)"


class Linear2StageBattery:
    """
    Two-stage linear battery model based on ACN-Sim.

    Reference: https://acnportal.readthedocs.io/en/latest/acnsim/models.html

    Stage 1 (CC):  soc < transition_soc
        effective_power = min(requested_power, max_power)
    Stage 2 (taper):  soc >= transition_soc
        effective_power = min(requested_power, max_power) *
                          (1 - soc) / (1 - transition_soc)
    """

    def __init__(
        self,
        capacity_kwh: float,
        init_soc_kwh: float = 0.0,
        max_power_kw: float = 7.0,
        transition_soc: float = 0.8,
    ) -> None:
        if capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be > 0")
        if not 0.0 <= transition_soc <= 1.0:
            raise ValueError("transition_soc must be in [0, 1]")
        self.capacity_kwh = float(capacity_kwh)
        self._charge_kwh = float(max(0.0, min(capacity_kwh, init_soc_kwh)))
        self.max_power_kw = float(max_power_kw)
        self.transition_soc = float(transition_soc)

    def soc_fraction(self) -> float:
        return self._charge_kwh / self.capacity_kwh

    def soc_kwh(self) -> float:
        return self._charge_kwh

    def is_full(self) -> bool:
        return self._charge_kwh >= self.capacity_kwh - 1e-9

    def _taper_factor(self) -> float:
        soc = self.soc_fraction()
        if soc < self.transition_soc:
            return 1.0
        denom = 1.0 - self.transition_soc
        if denom <= 1e-9:
            return 0.0
        return max(0.0, (1.0 - soc) / denom)

    def apply_power(self, requested_power_kw: float, hours: float) -> float:
        """Apply a charging command for `hours` of simulated time.

        Returns the actual average power (kW) that the battery accepted.
        """
        if hours <= 0 or requested_power_kw <= 0:
            return 0.0

        capped_power = min(requested_power_kw, self.max_power_kw)
        effective_power = capped_power * self._taper_factor()

        energy_kwh = effective_power * hours
        new_charge = self._charge_kwh + energy_kwh
        if new_charge > self.capacity_kwh:
            actual_energy = self.capacity_kwh - self._charge_kwh
            effective_power = actual_energy / hours if hours > 0 else 0.0
            self._charge_kwh = self.capacity_kwh
        else:
            self._charge_kwh = new_charge

        return effective_power

    def __repr__(self) -> str:
        return (
            f"Linear2StageBattery(capacity={self.capacity_kwh}kWh, "
            f"soc={self.soc_fraction()*100:.1f}%, "
            f"max_power={self.max_power_kw}kW, "
            f"transition={self.transition_soc}, "
            f"backend={battery_backend()})"
        )


if __name__ == "__main__":
    print(f"Backend: {battery_backend()}\n")
    b = Linear2StageBattery(
        capacity_kwh=60.0, init_soc_kwh=18.0,
        max_power_kw=7.0, transition_soc=0.8,
    )
    print(f"Initial: SOC={b.soc_fraction()*100:.1f}%, charge={b.soc_kwh():.2f} kWh")
    print()
    print(f"{'Tick':<6} {'Request (kW)':<14} {'Actual (kW)':<14} "
          f"{'SOC (%)':<10} {'Taper':<8}")
    print("-" * 55)
    for tick in range(1, 21):
        actual = b.apply_power(requested_power_kw=7.0, hours=0.5)
        taper = b._taper_factor()
        print(f"{tick:<6} {7.0:<14.2f} {actual:<14.2f} "
              f"{b.soc_fraction()*100:<10.1f} {taper:<8.2f}")
        if b.is_full():
            print(f"\nBattery full at tick {tick}")
            break