"""Tests for server/utils/math_helpers.py — wrap_angle and angle_diff."""
from __future__ import annotations

import pytest

from server.utils.math_helpers import angle_diff, wrap_angle


# ---------------------------------------------------------------------------
# wrap_angle
# ---------------------------------------------------------------------------


def test_wrap_angle_identity():
    assert wrap_angle(90.0) == pytest.approx(90.0)


def test_wrap_angle_zero():
    assert wrap_angle(0.0) == pytest.approx(0.0)


def test_wrap_angle_359():
    assert wrap_angle(359.0) == pytest.approx(359.0)


def test_wrap_angle_360_wraps_to_zero():
    assert wrap_angle(360.0) == pytest.approx(0.0)


def test_wrap_angle_negative_wraps():
    assert wrap_angle(-90.0) == pytest.approx(270.0)


def test_wrap_angle_large_positive():
    assert wrap_angle(720.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# angle_diff
# ---------------------------------------------------------------------------


def test_angle_diff_simple_clockwise():
    # 0 → 90 is 90° clockwise
    assert angle_diff(0.0, 90.0) == pytest.approx(90.0)


def test_angle_diff_simple_counter_clockwise():
    # 90 → 0 is -90° (counter-clockwise)
    assert angle_diff(90.0, 0.0) == pytest.approx(-90.0)


def test_angle_diff_shortest_path_across_zero():
    # 350 → 10: shortest path is +20°, not -340°
    assert angle_diff(350.0, 10.0) == pytest.approx(20.0)


def test_angle_diff_shortest_path_backward_across_zero():
    # 10 → 350: shortest path is -20°, not +340°
    assert angle_diff(10.0, 350.0) == pytest.approx(-20.0)


def test_angle_diff_same_angle_is_zero():
    assert angle_diff(180.0, 180.0) == pytest.approx(0.0)


def test_angle_diff_exactly_180_is_positive():
    # 180° difference returns +180 (canonical boundary value)
    assert angle_diff(0.0, 180.0) == pytest.approx(180.0)


def test_angle_diff_full_circle_is_zero():
    assert angle_diff(45.0, 405.0) == pytest.approx(0.0)
