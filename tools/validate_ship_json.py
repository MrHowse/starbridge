#!/usr/bin/env python3
"""Validate all ship class JSON files against the ShipClass schema.

Checks:
- Pydantic validation via load_ship_class()
- Required subfields: weapons, engines, sensors, shields, power_grid
- interior_layout references a valid interiors/{name}.json
- unique_systems entries are from a known set
- handling_trait is in VALID_HANDLING_TRAITS
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from project root or tools/.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.models.ship_class import (  # noqa: E402
    SHIP_CLASS_ORDER,
    VALID_HANDLING_TRAITS,
    load_ship_class,
)

INTERIORS_DIR = ROOT / "interiors"

KNOWN_UNIQUE_SYSTEMS: set[str] = {
    "stealth",
    "advanced_ecm",
    "flag_bridge",
    "dual_targeting",
    "spinal_mount",
    "armour_zones",
    "flight_centre",
    "hospital",
}

REQUIRED_WEAPON_FIELDS = {"beam_damage", "beam_fire_rate", "beam_arc", "beam_count"}
REQUIRED_SUBFIELDS = {"weapons", "engines", "sensors", "shields", "power_grid"}


def validate(class_id: str) -> list[str]:
    """Return list of error strings for *class_id* (empty = pass)."""
    errors: list[str] = []

    try:
        sc = load_ship_class(class_id)
    except Exception as exc:
        return [f"Failed to load: {exc}"]

    # Required sub-dicts present.
    for field in REQUIRED_SUBFIELDS:
        if getattr(sc, field) is None:
            errors.append(f"Missing required subfield: {field}")

    # Weapon subfields.
    if sc.weapons is not None:
        for wf in REQUIRED_WEAPON_FIELDS:
            if wf not in sc.weapons:
                errors.append(f"weapons missing key: {wf}")

    # handling_trait.
    if sc.handling_trait not in VALID_HANDLING_TRAITS:
        errors.append(f"Invalid handling_trait: {sc.handling_trait!r}")

    # interior_layout.
    if sc.interior_layout:
        layout_path = INTERIORS_DIR / f"{sc.interior_layout}.json"
        if not layout_path.exists():
            errors.append(f"interior_layout {sc.interior_layout!r} -> {layout_path} not found")
    else:
        errors.append("interior_layout is empty")

    # unique_systems.
    for us in sc.unique_systems:
        if us not in KNOWN_UNIQUE_SYSTEMS:
            errors.append(f"Unknown unique_system: {us!r}")

    return errors


def main() -> int:
    failed = False
    for cid in SHIP_CLASS_ORDER:
        errs = validate(cid)
        if errs:
            print(f"FAIL  {cid}:")
            for e in errs:
                print(f"  - {e}")
            failed = True
        else:
            print(f"PASS  {cid}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
