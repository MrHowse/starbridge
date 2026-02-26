"""Tests for ship silhouette SVG assets and client integration (§4.1)."""
import os
import xml.etree.ElementTree as ET

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BASE = os.path.join(os.path.dirname(__file__), "..")
_SVG_DIR = os.path.join(_BASE, "client", "shared", "silhouettes")

EXPECTED_CLASSES = [
    "scout",
    "corvette",
    "frigate",
    "cruiser",
    "battleship",
    "carrier",
    "medical_ship",
]


# ---------------------------------------------------------------------------
# D-1: SVG asset existence
# ---------------------------------------------------------------------------


class TestSilhouetteAssets:
    """Verify all 7 SVG files exist and are valid."""

    @pytest.mark.parametrize("ship_class", EXPECTED_CLASSES)
    def test_svg_file_exists(self, ship_class):
        path = os.path.join(_SVG_DIR, f"{ship_class}.svg")
        assert os.path.isfile(path), f"Missing silhouette: {path}"

    @pytest.mark.parametrize("ship_class", EXPECTED_CLASSES)
    def test_svg_is_valid_xml(self, ship_class):
        path = os.path.join(_SVG_DIR, f"{ship_class}.svg")
        tree = ET.parse(path)
        root = tree.getroot()
        # Should be an <svg> element (namespace-aware).
        assert root.tag.endswith("svg"), f"Root element is {root.tag}, expected svg"

    @pytest.mark.parametrize("ship_class", EXPECTED_CLASSES)
    def test_svg_has_viewbox(self, ship_class):
        path = os.path.join(_SVG_DIR, f"{ship_class}.svg")
        tree = ET.parse(path)
        root = tree.getroot()
        viewbox = root.get("viewBox")
        assert viewbox is not None, "SVG missing viewBox attribute"
        assert viewbox == "0 0 200 100", f"Unexpected viewBox: {viewbox}"

    @pytest.mark.parametrize("ship_class", EXPECTED_CLASSES)
    def test_svg_uses_monochrome_stroke(self, ship_class):
        """All silhouettes should use the terminal-green (#00ff41) primary stroke."""
        path = os.path.join(_SVG_DIR, f"{ship_class}.svg")
        with open(path) as f:
            content = f.read()
        assert "#00ff41" in content, "Primary stroke colour #00ff41 not found"

    @pytest.mark.parametrize("ship_class", EXPECTED_CLASSES)
    def test_svg_has_no_fill(self, ship_class):
        """Silhouettes should be outlines only (fill='none' on the main group)."""
        path = os.path.join(_SVG_DIR, f"{ship_class}.svg")
        with open(path) as f:
            content = f.read()
        assert 'fill="none"' in content

    def test_medical_ship_has_red_cross(self):
        path = os.path.join(_SVG_DIR, "medical_ship.svg")
        with open(path) as f:
            content = f.read()
        assert "#ff4040" in content, "Medical ship should have red cross marking"

    def test_no_extra_svg_files(self):
        """Only the 7 expected SVGs should exist (no stale assets)."""
        files = [f for f in os.listdir(_SVG_DIR) if f.endswith(".svg")]
        expected = {f"{c}.svg" for c in EXPECTED_CLASSES}
        assert set(files) == expected


# ---------------------------------------------------------------------------
# D-2: Wireframe integration
# ---------------------------------------------------------------------------


class TestWireframeIntegration:
    """Verify wireframe.js exports setShipClass and uses silhouette."""

    def test_wireframe_exports_set_ship_class(self):
        path = os.path.join(_BASE, "client", "captain", "wireframe.js")
        with open(path) as f:
            content = f.read()
        assert "export function setShipClass" in content

    def test_wireframe_draws_silhouette(self):
        path = os.path.join(_BASE, "client", "captain", "wireframe.js")
        with open(path) as f:
            content = f.read()
        assert "_shipSilhouetteImg" in content
        assert "drawImage" in content

    def test_captain_imports_set_ship_class(self):
        path = os.path.join(_BASE, "client", "captain", "captain.js")
        with open(path) as f:
            content = f.read()
        assert "setShipClass" in content


# ---------------------------------------------------------------------------
# D-3: Map renderer integration
# ---------------------------------------------------------------------------


class TestMapRendererIntegration:
    """Verify map_renderer.js has silhouette support."""

    def test_map_renderer_has_load_silhouette(self):
        path = os.path.join(_BASE, "client", "shared", "map_renderer.js")
        with open(path) as f:
            content = f.read()
        assert "loadShipSilhouette" in content

    def test_map_renderer_has_ship_icon_function(self):
        path = os.path.join(_BASE, "client", "shared", "map_renderer.js")
        with open(path) as f:
            content = f.read()
        assert "_drawShipIcon" in content

    def test_map_renderer_falls_back_to_chevron(self):
        """_drawShipIcon should call _drawShipChevron when no silhouette."""
        path = os.path.join(_BASE, "client", "shared", "map_renderer.js")
        with open(path) as f:
            content = f.read()
        # The fallback path should still reference the chevron.
        assert "_drawShipChevron" in content

    def test_captain_calls_load_silhouette(self):
        path = os.path.join(_BASE, "client", "captain", "captain.js")
        with open(path) as f:
            content = f.read()
        assert "loadShipSilhouette" in content


# ---------------------------------------------------------------------------
# D-4: Shield focus integration
# ---------------------------------------------------------------------------


class TestShieldFocusIntegration:
    """Verify weapons.js shield focus uses silhouette."""

    def test_weapons_loads_silhouette(self):
        path = os.path.join(_BASE, "client", "weapons", "weapons.js")
        with open(path) as f:
            content = f.read()
        assert "_sfSilhouetteImg" in content

    def test_weapons_draws_silhouette_in_shield_focus(self):
        path = os.path.join(_BASE, "client", "weapons", "weapons.js")
        with open(path) as f:
            content = f.read()
        # _drawShieldFocus should use the silhouette image.
        assert "drawImage" in content

    def test_weapons_radar_loads_silhouette(self):
        path = os.path.join(_BASE, "client", "weapons", "weapons.js")
        with open(path) as f:
            content = f.read()
        assert "loadShipSilhouette" in content


# ---------------------------------------------------------------------------
# §4.1.11: Enemy wireframe models
# ---------------------------------------------------------------------------


class TestEnemyWireframeModels:
    """Verify wireframe.js has models for all 7 ship classes."""

    SHIP_CLASS_MODELS = [
        "scout", "corvette", "frigate", "cruiser",
        "battleship", "carrier", "medical_ship",
    ]

    def _read_wireframe(self):
        path = os.path.join(_BASE, "client", "captain", "wireframe.js")
        with open(path) as f:
            return f.read()

    @pytest.mark.parametrize("ship_class", SHIP_CLASS_MODELS)
    def test_wireframe_model_exists(self, ship_class):
        content = self._read_wireframe()
        # Each model is defined as a key in WIREFRAME_MODELS.
        assert f"  {ship_class}:" in content or f"  {ship_class}: {{" in content, (
            f"WIREFRAME_MODELS missing model for '{ship_class}'"
        )

    def test_contact_model_key_uses_dynamic_lookup(self):
        """_contactModelKey should use WIREFRAME_MODELS[t] lookup, not hardcoded list."""
        content = self._read_wireframe()
        assert "WIREFRAME_MODELS[t]" in content

    def test_non_ship_types_preserved(self):
        """station, torpedo, friendly models must still exist."""
        content = self._read_wireframe()
        for key in ["station", "torpedo", "friendly"]:
            assert f"  {key}:" in content or f"  {key}: {{" in content


# ---------------------------------------------------------------------------
# §4.3.10: Lobby silhouette preview
# ---------------------------------------------------------------------------


class TestLobbySilhouettePreview:
    """Verify lobby shows ship silhouette and stat summary."""

    def test_lobby_html_has_preview_element(self):
        path = os.path.join(_BASE, "client", "lobby", "index.html")
        with open(path) as f:
            content = f.read()
        assert 'id="ship-preview"' in content
        assert 'id="ship-preview-img"' in content
        assert "silhouettes/" in content

    def test_lobby_js_has_ship_stats(self):
        path = os.path.join(_BASE, "client", "lobby", "lobby.js")
        with open(path) as f:
            content = f.read()
        assert "SHIP_STATS" in content

    @pytest.mark.parametrize("ship_class", EXPECTED_CLASSES)
    def test_lobby_js_has_stats_for_each_class(self, ship_class):
        path = os.path.join(_BASE, "client", "lobby", "lobby.js")
        with open(path) as f:
            content = f.read()
        assert f"  {ship_class}:" in content or f"'{ship_class}':" in content

    def test_lobby_js_updates_preview_on_change(self):
        path = os.path.join(_BASE, "client", "lobby", "lobby.js")
        with open(path) as f:
            content = f.read()
        assert "_updateShipPreview" in content
        assert "addEventListener" in content

    def test_lobby_css_has_preview_styles(self):
        path = os.path.join(_BASE, "client", "lobby", "lobby.css")
        with open(path) as f:
            content = f.read()
        assert ".ship-preview" in content
