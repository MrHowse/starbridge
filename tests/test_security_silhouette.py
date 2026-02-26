"""Tests for security station dynamic hull silhouette and adaptive layout."""
import os

import pytest

_BASE = os.path.join(os.path.dirname(__file__), "..")
_JS_PATH = os.path.join(_BASE, "client", "security", "security.js")
_HTML_PATH = os.path.join(_BASE, "client", "security", "index.html")
_LOBBY_PATH = os.path.join(_BASE, "server", "lobby.py")
_MAIN_PATH = os.path.join(_BASE, "server", "main.py")


@pytest.fixture()
def js_content():
    with open(_JS_PATH) as f:
        return f.read()


@pytest.fixture()
def html_content():
    with open(_HTML_PATH) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Ship class + silhouette loading
# ---------------------------------------------------------------------------


class TestSecuritySilhouette:

    def test_security_js_stores_ship_class(self, js_content):
        assert "_shipClass = payload.ship_class" in js_content

    def test_security_js_loads_silhouette(self, js_content):
        assert "/client/shared/silhouettes/" in js_content
        assert "new Image()" in js_content

    def test_security_js_no_hardcoded_hull_vertices(self, js_content):
        assert "HULL_VERTICES" not in js_content

    def test_security_js_no_hardcoded_deck_boundaries(self, js_content):
        # The old constant DECK_BOUNDARIES_Y = [...] should be gone;
        # the dynamic _deckBoundariesY variable is allowed.
        assert "const DECK_BOUNDARIES_Y" not in js_content
        assert "DECK_BOUNDARIES_Y =" not in js_content

    def test_security_js_computes_geometry(self, js_content):
        assert "function _computeGeometry" in js_content

    def test_security_js_draws_silhouette_image(self, js_content):
        assert "drawImage" in js_content
        assert "_hullImg" in js_content

    def test_security_js_has_fallback_hull(self, js_content):
        """Fallback rounded-rect when SVG not loaded."""
        assert "quadraticCurveTo" in js_content


# ---------------------------------------------------------------------------
# Dynamic deck controls
# ---------------------------------------------------------------------------


class TestSecurityDynamicControls:

    def test_security_js_no_hardcoded_deck_tabs(self, html_content):
        """HTML should not have hardcoded D1-D5 buttons."""
        assert 'data-deck="1"' not in html_content
        assert 'data-deck="5"' not in html_content
        # ALL button is kept
        assert 'data-deck="0"' in html_content

    def test_security_js_no_hardcoded_bulkhead_options(self, html_content):
        assert "SEAL D1-D2" not in html_content
        assert "UNSEAL D4-D5" not in html_content
        assert "BULKHEAD" in html_content  # header still present

    def test_security_js_no_hardcoded_arm_options(self, html_content):
        assert "ARM DECK 1" not in html_content
        assert "DISARM DECK 5" not in html_content
        assert "ARM CREW" in html_content  # header still present

    def test_security_js_populates_deck_controls(self, js_content):
        assert "function _populateDeckControls" in js_content
        # Should generate deck tabs, bulkhead options, and arm options
        assert "sel-bulkhead" in js_content
        assert "sel-arm" in js_content
        assert "deck-tabs" in js_content


# ---------------------------------------------------------------------------
# Server payload includes deck_number
# ---------------------------------------------------------------------------


class TestInteriorPayload:

    def test_lobby_includes_deck_number(self):
        with open(_LOBBY_PATH) as f:
            content = f.read()
        assert '"deck_number": room.deck_number' in content

    def test_main_includes_deck_number(self):
        with open(_MAIN_PATH) as f:
            content = f.read()
        assert '"deck_number": room.deck_number' in content

    def test_security_js_uses_deck_number(self, js_content):
        """_computeGeometry should use deck_number, not parseInt(deck)."""
        assert "r.deck_number" in js_content
