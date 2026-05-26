"""Unit tests for testable logic in first_run.py.

Most of first_run.py is tkinter UI code or async network calls —
neither is suitable for pure unit tests. This file covers:

- _default_machine_name: hostname resolution with fallback
- _resolve_mtgo_log_dir: directory resolution logic (mocked filesystem)
- _prompt_code_stdin / _prompt_method_stdin: stdin-based input paths

UI-driven functions (_prompt_code_tk, _prompt_method_tk,
_prompt_email_password_tk, _prompt_agent_name, _prompt_mtgo_dir_tk)
are skipped because they create real tkinter windows and block on
mainloop — testing them requires a display server or tkinter stubs
that add more complexity than value.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.first_run import (
    _default_machine_name,
    _prompt_code_stdin,
    _prompt_method_stdin,
    _resolve_mtgo_log_dir,
)

# --- _default_machine_name ---


class TestDefaultMachineName:
    def test_returns_hostname(self) -> None:
        """Under normal conditions, returns the actual hostname string."""
        name = _default_machine_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_fallback_when_gethostname_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If socket.gethostname() raises, falls back to 'unknown'."""
        monkeypatch.setattr(socket, "gethostname", lambda: (_ for _ in ()).throw(OSError("fail")))
        monkeypatch.setattr("platform.node", lambda: "")
        assert _default_machine_name() == "unknown"

    def test_fallback_when_gethostname_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If gethostname returns empty, falls through to platform.node."""
        monkeypatch.setattr(socket, "gethostname", lambda: "")
        monkeypatch.setattr("platform.node", lambda: "my-platform-node")
        assert _default_machine_name() == "my-platform-node"

    def test_fallback_when_both_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If gethostname and platform.node both return empty, returns 'unknown'."""
        monkeypatch.setattr(socket, "gethostname", lambda: "")
        monkeypatch.setattr("platform.node", lambda: "")
        assert _default_machine_name() == "unknown"


# --- _resolve_mtgo_log_dir ---


class TestResolveMtgoLogDir:
    def test_uses_default_when_dir_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the default MTGO dir exists, it is used without prompting."""
        default_dir = tmp_path / "Apps" / "2.0"
        default_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "deep_analysis_agent.first_run._default_mtgo_log_dir", lambda: default_dir
        )
        config = AppConfig()
        _resolve_mtgo_log_dir(config)
        assert config.mtgo.log_dir == default_dir

    def test_falls_back_to_default_when_prompt_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When default doesn't exist and user cancels the prompt, keeps the default path."""
        default_dir = tmp_path / "Apps" / "2.0"  # does NOT exist
        monkeypatch.setattr(
            "deep_analysis_agent.first_run._default_mtgo_log_dir", lambda: default_dir
        )
        monkeypatch.setattr("deep_analysis_agent.first_run._prompt_mtgo_dir_tk", lambda: None)
        config = AppConfig()
        _resolve_mtgo_log_dir(config)
        # Falls back to the default path even though it doesn't exist.
        assert config.mtgo.log_dir == default_dir

    def test_uses_user_selected_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When default doesn't exist but user picks a valid dir, uses that."""
        default_dir = tmp_path / "nonexistent"
        chosen_dir = tmp_path / "user_picked"
        chosen_dir.mkdir()
        monkeypatch.setattr(
            "deep_analysis_agent.first_run._default_mtgo_log_dir", lambda: default_dir
        )
        monkeypatch.setattr(
            "deep_analysis_agent.first_run._prompt_mtgo_dir_tk", lambda: str(chosen_dir)
        )
        config = AppConfig()
        _resolve_mtgo_log_dir(config)
        assert config.mtgo.log_dir == chosen_dir


# --- _prompt_code_stdin ---


class TestPromptCodeStdin:
    def test_returns_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "ABCD-1234")
        result = _prompt_code_stdin()
        assert result == "ABCD-1234"

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "  ABCD-1234  ")
        result = _prompt_code_stdin()
        assert result == "ABCD-1234"

    def test_empty_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        result = _prompt_code_stdin()
        assert result is None

    def test_eof_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_eof(_prompt: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise_eof)
        result = _prompt_code_stdin()
        assert result is None


# --- _prompt_method_stdin ---


class TestPromptMethodStdin:
    def test_choice_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "1")
        assert _prompt_method_stdin() == 1

    def test_choice_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "2")
        assert _prompt_method_stdin() == 2

    def test_blank_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        assert _prompt_method_stdin() is None

    def test_invalid_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "3")
        assert _prompt_method_stdin() is None

    def test_eof_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_eof(_prompt: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise_eof)
        assert _prompt_method_stdin() is None
