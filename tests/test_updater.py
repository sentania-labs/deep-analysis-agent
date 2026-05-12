"""Tests for the updater module."""

from __future__ import annotations

import sys
from unittest.mock import patch

from deep_analysis_agent.updater import UpdateCheckResult, check_for_update


def test_check_returns_unavailable_when_not_frozen() -> None:
    with patch.object(sys, "frozen", False, create=True):
        result = check_for_update("0.4.9")
    assert result.available is False
    assert "dev build" in result.message


def test_update_check_result_dataclass() -> None:
    r = UpdateCheckResult(available=True, message="v0.5.0 available")
    assert r.available is True
    assert r.message == "v0.5.0 available"
