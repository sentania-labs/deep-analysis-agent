"""Unit tests for testable logic in first_run.py.

Most of first_run.py is tkinter UI code or async network calls —
neither is suitable for pure unit tests. This file covers:

- _default_machine_name: hostname resolution with fallback
- _resolve_mtgo_log_dir: directory resolution logic (mocked filesystem)
- _prompt_code_stdin / _prompt_method_stdin: stdin-based input paths

- run_first_run_flow: registration failure reporting and retry, driven
  against the `fake_tk` fixture in conftest.py (scripted, window-free
  tkinter stand-ins, so nothing opens a window or blocks on mainloop)

_prompt_method_tk and _prompt_mtgo_dir_tk build a real widget tree, so
they are still driven by monkeypatching the function rather than the
widgets. Nothing here proves how a dialog looks on a real desktop, only
which dialog is invoked with which message.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from deep_analysis_agent import auth
from deep_analysis_agent.config import AppConfig
from deep_analysis_agent.first_run import (
    _default_machine_name,
    _prompt_agent_name,
    _prompt_code,
    _prompt_code_stdin,
    _prompt_email_password,
    _prompt_method,
    _prompt_method_stdin,
    _report_registration_failure,
    _resolve_mtgo_log_dir,
    run_first_run_flow,
)

from .conftest import FakeTkinter

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


# --- run_first_run_flow: GUI error visibility (agent issue #44) ---
#
# The defect: on the email/password path a RegistrationError was reported
# with `print()` and the flow exited. The shipped agent is a tray app with
# no console, so the user saw it vanish. These tests drive
# `run_first_run_flow` against the `fake_tk` fixture, which replaces the
# tkinter modules in sys.modules with scripted, window-free stand-ins.
#
# What these prove: which dialog function is called, with what message,
# how many registration attempts happen, and that no code path reads
# stdin while tkinter is available. What they cannot prove: that the
# dialog is legible, correctly parented, or on top on a real Windows
# desktop. That needs a display.


def _flow_env(monkeypatch: pytest.MonkeyPatch, method: int) -> list[str]:
    """Pin the flow to `method`, stub out config persistence.

    Returns the list that records saved configs.
    """
    saved: list[str] = []
    monkeypatch.setattr("deep_analysis_agent.first_run._prompt_method_tk", lambda: method)
    monkeypatch.setattr("deep_analysis_agent.first_run._resolve_mtgo_log_dir", lambda _config: None)
    monkeypatch.setattr(
        "deep_analysis_agent.first_run.save_config",
        lambda config: saved.append(config.agent.agent_id or ""),
    )
    return saved


def _result() -> auth.RegistrationResult:
    return auth.RegistrationResult(agent_id="agent-1", api_token="tok", user_id=7)


def _scripted_register(
    outcomes: list[object],
    calls: list[dict[str, object]],
) -> Callable[..., Awaitable[auth.RegistrationResult]]:
    """Async stub returning/raising `outcomes` in order, recording kwargs."""

    async def _register(_url: str, **kwargs: object) -> auth.RegistrationResult:
        calls.append(kwargs)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, auth.RegistrationResult)
        return outcome

    return _register


class TestCredentialsFailureIsVisible:
    def test_failure_shows_retry_dialog_and_second_attempt_succeeds(
        self,
        fake_tk: FakeTkinter,
        no_stdin: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A bad password surfaces a dialog, and the retry gets through."""
        _flow_env(monkeypatch, method=1)
        fake_tk.answers = {
            "email": ["me@example.com", "me@example.com"],
            "password": ["wrong", "right"],
            "agent name": None,
        }
        fake_tk.askretrycancel_answers = [True]
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth,
            "register_with_credentials",
            _scripted_register(
                [auth.RegistrationError("invalid email or password"), _result()], calls
            ),
        )

        ok = asyncio.run(run_first_run_flow(AppConfig()))

        assert ok is True
        assert len(calls) == 2
        assert calls[1]["password"] == "right"
        # The failure reached the user through a dialog, not stdout.
        assert len(fake_tk.askretrycancel_calls) == 1
        assert "invalid email or password" in fake_tk.askretrycancel_calls[0][1]
        assert "Registration failed" not in capsys.readouterr().out
        assert fake_tk.roots_created == fake_tk.roots_destroyed

    def test_exhausting_attempts_shows_error_dialog_not_print(
        self,
        fake_tk: FakeTkinter,
        no_stdin: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Three failures end in showerror, and the flow reports False."""
        _flow_env(monkeypatch, method=1)
        fake_tk.answers = {
            "email": "me@example.com",
            "password": "wrong",
            "agent name": None,
        }
        fake_tk.askretrycancel_answers = [True, True]
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth,
            "register_with_credentials",
            _scripted_register(
                [auth.RegistrationError("server returned 500") for _ in range(3)], calls
            ),
        )

        ok = asyncio.run(run_first_run_flow(AppConfig()))

        assert ok is False
        assert len(calls) == 3
        assert len(fake_tk.askretrycancel_calls) == 2
        assert len(fake_tk.showerror_calls) == 1
        assert "server returned 500" in fake_tk.showerror_calls[0][1]
        assert "Registration failed" not in capsys.readouterr().out
        assert fake_tk.roots_created == fake_tk.roots_destroyed

    def test_declining_retry_stops_immediately(
        self,
        fake_tk: FakeTkinter,
        no_stdin: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancel on the retry dialog means one attempt only."""
        _flow_env(monkeypatch, method=1)
        fake_tk.answers = {
            "email": "me@example.com",
            "password": "wrong",
            "agent name": None,
        }
        fake_tk.askretrycancel_answers = [False]
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth,
            "register_with_credentials",
            _scripted_register([auth.RegistrationError("nope")], calls),
        )

        assert asyncio.run(run_first_run_flow(AppConfig())) is False
        assert len(calls) == 1


class TestCancelDoesNotFallBackToStdin:
    """A cancelled dialog is not the same condition as absent tkinter.

    Falling through to `input()`/`getpass()` after a cancel is an
    invisible hang in a windowed app. The `no_stdin` fixture turns any
    such read into a test failure.
    """

    def test_cancelling_email_dialog_does_not_read_stdin(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _flow_env(monkeypatch, method=1)
        fake_tk.answers = {"email": None}
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth, "register_with_credentials", _scripted_register([_result()], calls)
        )

        assert asyncio.run(run_first_run_flow(AppConfig())) is False
        assert calls == []

    def test_cancelling_password_dialog_does_not_read_stdin(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _flow_env(monkeypatch, method=1)
        fake_tk.answers = {"email": "me@example.com", "password": None}
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth, "register_with_credentials", _scripted_register([_result()], calls)
        )

        assert asyncio.run(run_first_run_flow(AppConfig())) is False
        assert calls == []

    def test_prompt_email_password_returns_none_on_cancel(
        self, fake_tk: FakeTkinter, no_stdin: None
    ) -> None:
        """The wrapper itself, not just the flow, refuses the fallback."""
        fake_tk.answers = {"email": None}
        assert _prompt_email_password() is None

    def test_cancelling_code_dialog_does_not_read_stdin(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _flow_env(monkeypatch, method=2)
        fake_tk.answers = {"registration code": None}
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(auth, "register", _scripted_register([_result()], calls))

        assert asyncio.run(run_first_run_flow(AppConfig())) is False
        assert calls == []

    def test_blank_code_is_a_cancel_not_a_fallback(
        self, fake_tk: FakeTkinter, no_stdin: None
    ) -> None:
        """A whitespace-only code used to look like 'tkinter unavailable'."""
        fake_tk.answers = {"registration code": "   "}
        assert _prompt_code() is None

    def test_missing_tkinter_still_falls_back_to_stdin(
        self, no_tkinter: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fallback is preserved for the condition it was meant for."""
        monkeypatch.setattr("builtins.input", lambda _prompt: "ABCD-1234")
        assert _prompt_code() == "ABCD-1234"


class TestCodePathUnchanged:
    def test_retries_and_succeeds_on_second_code(
        self,
        fake_tk: FakeTkinter,
        no_stdin: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _flow_env(monkeypatch, method=2)
        fake_tk.answers = {"registration code": ["BAD-0000", "GOOD-1111"]}
        fake_tk.askretrycancel_answers = [True]
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth,
            "register",
            _scripted_register(
                [auth.RegistrationError("invalid or expired registration code"), _result()],
                calls,
            ),
        )

        assert asyncio.run(run_first_run_flow(AppConfig())) is True
        assert [c["code"] for c in calls] == ["BAD-0000", "GOOD-1111"]
        assert len(fake_tk.askretrycancel_calls) == 1

    def test_gives_up_after_three_failures(
        self,
        fake_tk: FakeTkinter,
        no_stdin: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Still three attempts, as before, now ending in a visible error."""
        _flow_env(monkeypatch, method=2)
        fake_tk.answers = {"registration code": "BAD-0000"}
        fake_tk.askretrycancel_answers = [True, True]
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth,
            "register",
            _scripted_register([auth.RegistrationError("bad code") for _ in range(3)], calls),
        )

        assert asyncio.run(run_first_run_flow(AppConfig())) is False
        assert len(calls) == 3
        assert len(fake_tk.showerror_calls) == 1
        assert "Registration failed" not in capsys.readouterr().out
        assert fake_tk.roots_created == fake_tk.roots_destroyed

    def test_success_saves_config(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saved = _flow_env(monkeypatch, method=2)
        fake_tk.answers = {"registration code": "GOOD-1111"}
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(auth, "register", _scripted_register([_result()], calls))
        config = AppConfig()

        assert asyncio.run(run_first_run_flow(config)) is True
        assert saved == ["agent-1"]
        assert config.agent.agent_id == "agent-1"


class TestReportRegistrationFailure:
    def test_falls_back_to_print_without_tkinter(
        self, no_tkinter: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Headless is the one case where stdout is the right channel."""
        assert _report_registration_failure("boom", can_retry=True) is True
        assert "Registration failed: boom" in capsys.readouterr().out

    def test_no_retry_offer_when_attempts_exhausted(self, fake_tk: FakeTkinter) -> None:
        assert _report_registration_failure("boom", can_retry=False) is False
        assert fake_tk.askretrycancel_calls == []
        assert len(fake_tk.showerror_calls) == 1

    def test_destroys_its_root_window(self, fake_tk: FakeTkinter) -> None:
        """Leaked Tk roots stack up across retries; make sure they don't."""
        fake_tk.askretrycancel_answers = [True]
        _report_registration_failure("boom", can_retry=True)
        assert fake_tk.roots_created == fake_tk.roots_destroyed == 1


class TestTkAvailabilityIsNarrowlyDefined:
    """Only "cannot import" / "cannot make a root" may reach stdin.

    A dialog that raises while the GUI is up is a decline, not a licence
    to block on a console read. These lock that distinction in.
    """

    def test_dialog_exception_is_treated_as_cancel_not_as_headless(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: object, **_kw: object) -> str:
            raise RuntimeError("X server went away mid-dialog")

        monkeypatch.setattr("tkinter.simpledialog.askstring", _boom)
        assert _prompt_email_password() is None
        assert _prompt_code() is None

    def test_root_creation_failure_is_headless(
        self, fake_tk: FakeTkinter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No display means no GUI, so stdin is the right channel."""

        def _no_display() -> object:
            raise RuntimeError("no display name and no $DISPLAY")

        monkeypatch.setattr("tkinter.Tk", _no_display)
        monkeypatch.setattr("builtins.input", lambda _prompt: "ABCD-1234")
        assert _prompt_code() == "ABCD-1234"

    def test_missing_tkinter_falls_back_for_credentials(
        self, no_tkinter: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "me@example.com")
        monkeypatch.setattr("getpass.getpass", lambda _prompt: "pw")
        assert _prompt_email_password() == ("me@example.com", "pw")

    def test_missing_tkinter_falls_back_for_method(
        self, no_tkinter: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("builtins.input", lambda _prompt: "2")
        assert _prompt_method() == 2

    def test_agent_name_dialog_failure_uses_default_not_stdin(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: object, **_kw: object) -> str:
            raise RuntimeError("dialog exploded")

        monkeypatch.setattr("tkinter.simpledialog.askstring", _boom)
        assert _prompt_agent_name("fallback-name") == "fallback-name"


class TestAgentNameAskedOncePerFlow:
    def test_retry_does_not_reprompt_for_agent_name(
        self, fake_tk: FakeTkinter, no_stdin: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-asking the name after a bad password reads as a bug to a user."""
        _flow_env(monkeypatch, method=1)
        fake_tk.answers = {
            "email": ["me@example.com", "me@example.com"],
            "password": ["wrong", "right"],
            "agent name": "my-desk",
        }
        fake_tk.askretrycancel_answers = [True]
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            auth,
            "register_with_credentials",
            _scripted_register([auth.RegistrationError("nope"), _result()], calls),
        )

        assert asyncio.run(run_first_run_flow(AppConfig())) is True
        assert sum("agent name" in p.lower() for p in fake_tk.askstring_calls) == 1
        assert [c["agent_name"] for c in calls] == ["my-desk", "my-desk"]
