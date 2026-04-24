"""Smoke test for the icon-cycling cadence constant."""

from __future__ import annotations

from deep_analysis_agent import tray


def test_pip_cycle_seconds_per_color_is_two_seconds() -> None:
    assert tray.PIP_CYCLE_SECONDS_PER_COLOR == 2.0
