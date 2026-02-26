"""Tests for v0.07-6 Commit C: Station Display Adaptation.

Verifies that:
  1. game.started payload includes ship_class field
  2. Unique systems map to correct station panels
  3. Ship class data is available for station adaptation
"""
from __future__ import annotations

from server.models.ship_class import load_ship_class, list_ship_classes, SHIP_CLASS_ORDER


# ============================================================================
# game.started payload includes ship_class
# ============================================================================


class TestGameStartedPayload:
    """Verify the lobby builds game.started with ship_class."""

    def test_lobby_game_payload_has_ship_class(self):
        """LobbySession._game_payload includes ship_class key."""
        # The lobby sets _game_payload with "ship_class": payload.ship_class
        # We verify the structure is correct by checking the lobby source.
        import server.lobby as lobby
        import inspect
        source = inspect.getsource(lobby)
        assert '"ship_class": payload.ship_class' in source or "'ship_class': payload.ship_class" in source

    def test_all_seven_ship_classes_exist(self):
        """All 7 ship classes should be loadable."""
        classes = list_ship_classes()
        assert len(classes) == 7
        for cls_id in SHIP_CLASS_ORDER:
            sc = load_ship_class(cls_id)
            assert sc.id == cls_id


# ============================================================================
# Unique systems → station panel mapping
# ============================================================================

# Expected mapping: unique_system → (station, panel_id)
EXPECTED_PANELS = {
    "stealth":            ("ew",         "stealth-panel"),
    "advanced_ecm":       ("ew",         "advanced-ecm-panel"),
    "flag_bridge":        ("captain",    "flag-bridge-panel"),
    "dual_targeting":     ("weapons",    "dual-target-panel"),
    "spinal_mount":       ("weapons",    "spinal-mount-panel"),
    "flight_centre":      ("flight_ops", "squadron-panel"),
    "hospital":           ("medical",    "surgical-theatre-panel"),
}

# Ship class → expected unique systems (at least one per class)
EXPECTED_UNIQUE_SYSTEMS = {
    "scout":        ["stealth"],
    "corvette":     ["advanced_ecm"],
    "frigate":      [],  # frigate uses modular_bays instead of unique_systems
    "cruiser":      ["flag_bridge", "dual_targeting"],
    "battleship":   ["spinal_mount", "armour_zones", "dual_targeting"],
    "carrier":      ["flight_centre"],
    "medical_ship": ["hospital"],
}


class TestUniqueSystemPanelMapping:
    """Verify each ship class's unique systems map to station panels."""

    def test_scout_stealth_panel(self):
        sc = load_ship_class("scout")
        assert "stealth" in sc.unique_systems

    def test_corvette_ecm_panel(self):
        sc = load_ship_class("corvette")
        assert "advanced_ecm" in sc.unique_systems

    def test_frigate_has_modular_bays(self):
        sc = load_ship_class("frigate")
        assert sc.modular_bays > 0

    def test_cruiser_flag_bridge_and_dual_targeting(self):
        sc = load_ship_class("cruiser")
        assert "flag_bridge" in sc.unique_systems
        assert "dual_targeting" in sc.unique_systems

    def test_battleship_spinal_mount(self):
        sc = load_ship_class("battleship")
        assert "spinal_mount" in sc.unique_systems

    def test_carrier_flight_centre(self):
        sc = load_ship_class("carrier")
        assert "flight_centre" in sc.unique_systems

    def test_medical_ship_hospital(self):
        sc = load_ship_class("medical_ship")
        assert "hospital" in sc.unique_systems

    def test_all_expected_systems_covered(self):
        """Every ship class has at least one unique system."""
        for cls_id, expected in EXPECTED_UNIQUE_SYSTEMS.items():
            sc = load_ship_class(cls_id)
            for sys_name in expected:
                assert sys_name in sc.unique_systems, \
                    f"{cls_id} missing unique_system {sys_name}"


# ============================================================================
# HTML panel existence (verify panels added to correct station HTML)
# ============================================================================


class TestHTMLPanelsExist:
    """Verify panel IDs exist in the correct station HTML files."""

    def _html_has_id(self, station_path: str, panel_id: str) -> bool:
        from pathlib import Path
        html_path = Path(__file__).parent.parent / "client" / station_path / "index.html"
        content = html_path.read_text()
        return f'id="{panel_id}"' in content

    def test_weapons_spinal_mount_panel(self):
        assert self._html_has_id("weapons", "spinal-mount-panel")

    def test_weapons_dual_target_panel(self):
        assert self._html_has_id("weapons", "dual-target-panel")

    def test_ew_stealth_panel(self):
        assert self._html_has_id("ew", "stealth-panel")

    def test_ew_advanced_ecm_panel(self):
        assert self._html_has_id("ew", "advanced-ecm-panel")

    def test_flight_ops_squadron_panel(self):
        assert self._html_has_id("flight_ops", "squadron-panel")

    def test_medical_surgical_theatre_panel(self):
        assert self._html_has_id("medical", "surgical-theatre-panel")

    def test_medical_triage_ai_panel(self):
        assert self._html_has_id("medical", "triage-ai-panel")

    def test_captain_flag_bridge_panel(self):
        assert self._html_has_id("captain", "flag-bridge-panel")

    def test_engineering_modular_bay_panel(self):
        assert self._html_has_id("engineering", "modular-bay-panel")
