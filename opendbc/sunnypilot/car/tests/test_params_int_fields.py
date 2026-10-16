"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import dataclasses
import re
from pathlib import Path

import pytest

from opendbc.car import gen_empty_fingerprint
from opendbc.car.car_helpers import interfaces
from opendbc.car.interfaces import get_interface_attr
from opendbc.car.vin import VIN_UNKNOWN
from opendbc.sunnypilot.car.interfaces import setup_interfaces

# card serializes CarParams and CarParamsSP with pycapnp, which rejects any int subclass. OR-ing a
# bare IntFlag member into a field (`ret.flags |= XFlags.Y`) leaves an IntFlag there, behaves like an
# int everywhere in Python, and only crashes card after fingerprinting.

OPENDBC = Path(__file__).resolve().parents[3]
VIN_TAIL = "KF4WLA10114918"
# every brand-gated toggle setup_interfaces reads, switched on
ALL_TOGGLES = [{
  "HyundaiLongitudinalTuning": "1",
  "MazdaTjaButton": "1",
  "SubaruStopAndGo": "1",
  "SubaruStopAndGoManualParkingBrake": "1",
  "TeslaCoopSteering": "1",
  "TeslaMadsScreenButton": "1",
  "ToyotaEnforceStockLongitudinal": "1",
  "ToyotaStopAndGoHack": "1",
}]
WMIS = get_interface_attr("WMI", ignore_none=True)


def _vins(brand: str) -> list[str]:
  return [VIN_UNKNOWN] + [str(wmi) + VIN_TAIL for wmi in WMIS.get(brand, [])]


def _int_subclasses(obj, path: str = ""):
  if dataclasses.is_dataclass(obj):
    for f in dataclasses.fields(obj):
      yield from _int_subclasses(getattr(obj, f.name), f"{path}.{f.name}")
  elif isinstance(obj, (list, tuple)):
    for i, v in enumerate(obj):
      yield from _int_subclasses(v, f"{path}[{i}]")
  elif isinstance(obj, int) and type(obj) not in (int, bool):
    yield path, obj


@pytest.mark.parametrize("platform", sorted(p for p in interfaces if p != "MOCK"))
def test_params_hold_plain_ints(platform):
  CarInterface = interfaces[platform]
  brand = CarInterface.__module__.split(".")[2]
  for vin in _vins(brand):
    for alpha_long in (False, True):
      for params_list in (None, ALL_TOGGLES):
        CP = CarInterface.get_params(platform, gen_empty_fingerprint(), [], alpha_long, False, docs=False)
        CP.carVin = vin
        CP_SP = CarInterface.get_params_sp(CP, platform, gen_empty_fingerprint(), [], alpha_long, False, docs=False)
        setup_interfaces(CarInterface, CP, CP_SP, params_list, lambda *a, **k: [], lambda *a, **k: None)

        bad = [*_int_subclasses(CP, "CP"), *_int_subclasses(CP_SP, "CP_SP")]
        assert not bad, f"{platform} vin={vin} alpha_long={alpha_long} toggles={params_list is not None}: " + \
                        ", ".join(f"{p}={v!r}" for p, v in bad)


def test_no_bare_flag_members_assigned_to_params():
  # Catches the branches the runtime test cannot reach (fw-, CAN- or param-gated). PlatformConfig's
  # own `self.flags |= XFlags.Y` is fine: interfaces.py stores it as int(platform.config.flags).
  sources = [p for p in OPENDBC.rglob("*.py") if "tests" not in p.parts]
  enum_classes = {m for p in sources for m in re.findall(r"^class (\w+)\((?:IntFlag|IntEnum)\):", p.read_text(), re.M)}
  member = rf"(?:{'|'.join(sorted(enum_classes))})\.[A-Z][A-Z0-9_]*"
  bare = re.compile(rf"^\s*(?!self\.)\w+(?:\.\w+)+\s*\|?=\s*{member}(?:\s*\|\s*{member})*\s*(?:#.*)?$")

  hits = [f"{p.relative_to(OPENDBC)}:{i}: {line.strip()}"
          for p in sources for i, line in enumerate(p.read_text().splitlines(), 1) if bare.match(line)]
  assert not hits, "store .value (or int(...)), capnp rejects IntFlag:\n" + "\n".join(hits)
