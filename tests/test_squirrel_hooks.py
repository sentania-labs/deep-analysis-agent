"""Unit tests for Squirrel.Windows lifecycle hook handling in main.py."""

from __future__ import annotations

import sys

import pytest

from deep_analysis_agent.main import _handle_squirrel_hooks


@pytest.mark.parametrize(
    "hook",
    [
        "--squirrel-install",
        "--squirrel-updated",
        "--squirrel-obsolete",
        "--squirrel-uninstall",
    ],
)
def test_squirrel_hook_recognized(monkeypatch: pytest.MonkeyPatch, hook: str) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", hook])
    assert _handle_squirrel_hooks() is True


def test_no_arg_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe"])
    assert _handle_squirrel_hooks() is False


def test_unknown_arg_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["DeepAnalysisAgent.exe", "--some-other-flag"])
    assert _handle_squirrel_hooks() is False
