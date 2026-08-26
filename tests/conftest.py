"""Shared test fixtures.

The helpers here are the single place the ingest upload contract is
encoded on the test side. They mirror the server's ``UploadResponse``
(deep-analysis-server: ``services/ingest/ingest_service/schemas.py``)
exactly, so a fake upload response in any test cannot quietly describe
an API the server does not actually serve.

Agent issue #40 happened because each test hand-rolled its own upload
payload with a ``file_id`` key that the server has never returned. Build
fake upload responses through :func:`upload_response` instead.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

# Exact field set of the server's ``UploadResponse``. If the server adds,
# removes, or renames a field, change it here and every upload test moves
# with it.
UPLOAD_RESPONSE_FIELDS = frozenset({"sha256", "size_bytes", "deduped", "upload_id"})

# ``POST /ingest/upload`` is declared with ``status_code=201``.
UPLOAD_CREATED_STATUS = 201


def upload_response(
    *,
    deduped: bool,
    upload_id: int,
    sha256: str = "a" * 64,
    size_bytes: int = 17,
) -> dict[str, Any]:
    """Build a JSON body shaped exactly like the server's ``UploadResponse``.

    ``deduped`` and ``upload_id`` are required because they are the two
    fields the agent actually consumes. The build is validated against
    :data:`UPLOAD_RESPONSE_FIELDS` so a stray or missing key fails loudly
    rather than silently teaching the agent a wrong contract.
    """
    body: dict[str, Any] = {
        "sha256": sha256,
        "size_bytes": size_bytes,
        "deduped": deduped,
        "upload_id": upload_id,
    }
    assert set(body) == UPLOAD_RESPONSE_FIELDS, (
        f"upload_response drifted from the server contract: "
        f"{sorted(set(body) ^ UPLOAD_RESPONSE_FIELDS)}"
    )
    return body


# --- Fake tkinter -----------------------------------------------------------
#
# first_run.py imports tkinter lazily *inside* each prompt function, so
# replacing the entries in ``sys.modules`` is enough to intercept every
# dialog. Nothing below opens a window, which is the point: these tests
# must run headless in CI, and a real ``simpledialog`` would block forever.


class FakeTkMisuse(BaseException):
    """Raised when a test scripts the fake tkinter wrongly.

    Derived from BaseException on purpose: `first_run.py` wraps every
    dialog in `except Exception`, so a plain AssertionError here would be
    swallowed and resurface as some unrelated fallback behaviour, sending
    the next test author after the wrong bug.
    """


class _FakeRoot:
    """Stand-in for ``tkinter.Tk()``. Records lifecycle, opens nothing."""

    def __init__(self, tk: FakeTkinter) -> None:
        self._tk = tk
        tk.roots_created += 1

    def withdraw(self) -> None:
        pass

    def destroy(self) -> None:
        self._tk.roots_destroyed += 1

    def title(self, *_args: Any, **_kw: Any) -> None:
        pass

    def resizable(self, *_args: Any, **_kw: Any) -> None:
        pass

    def protocol(self, *_args: Any, **_kw: Any) -> None:
        pass

    def mainloop(self) -> None:
        # No widget tree is simulated, so there is nothing to pump. Tests
        # that need a specific method choice monkeypatch
        # ``first_run._prompt_method_tk`` directly.
        pass


class FakeTkinter:
    """Scripted replacement for the tkinter modules ``first_run`` imports.

    ``answers`` maps a lowercase substring of a dialog prompt to the value
    ``askstring`` should return. A list value is consumed one entry per
    call, which is how a retry sequence is expressed (first attempt gets a
    bad password, second gets a good one). ``None`` means the user hit
    Cancel.

    ``askretrycancel_answers`` works the same way for the retry prompt.
    """

    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}
        self.askretrycancel_answers: list[bool] = []
        self.askstring_calls: list[str] = []
        self.showerror_calls: list[tuple[str, str]] = []
        self.askretrycancel_calls: list[tuple[str, str]] = []
        self.roots_created = 0
        self.roots_destroyed = 0

    # -- recorded dialog implementations --

    def askstring(self, _title: str, prompt: str, **_kw: Any) -> str | None:
        self.askstring_calls.append(prompt)
        key = prompt.lower()
        for needle, value in self.answers.items():
            if needle in key:
                if isinstance(value, list):
                    if not value:
                        raise FakeTkMisuse(f"FakeTkinter ran out of answers for {needle!r}")
                    return value.pop(0)
                return value
        raise FakeTkMisuse(f"FakeTkinter has no scripted answer for prompt {prompt!r}")

    def showerror(self, title: str, message: str, **_kw: Any) -> str:
        self.showerror_calls.append((title, message))
        return "ok"

    def askretrycancel(self, title: str, message: str, **_kw: Any) -> bool:
        self.askretrycancel_calls.append((title, message))
        if not self.askretrycancel_answers:
            raise FakeTkMisuse("FakeTkinter has no scripted askretrycancel answer left")
        return self.askretrycancel_answers.pop(0)

    def askdirectory(self, **_kw: Any) -> str:
        return ""


def _install_fake_tkinter(monkeypatch: Any) -> FakeTkinter:
    fake = FakeTkinter()

    tk_mod = types.ModuleType("tkinter")
    tk_mod.Tk = lambda: _FakeRoot(fake)  # type: ignore[attr-defined]
    tk_mod.IntVar = lambda **_kw: None  # type: ignore[attr-defined]

    simpledialog_mod = types.ModuleType("tkinter.simpledialog")
    simpledialog_mod.askstring = fake.askstring  # type: ignore[attr-defined]

    messagebox_mod = types.ModuleType("tkinter.messagebox")
    messagebox_mod.showerror = fake.showerror  # type: ignore[attr-defined]
    messagebox_mod.askretrycancel = fake.askretrycancel  # type: ignore[attr-defined]

    filedialog_mod = types.ModuleType("tkinter.filedialog")
    filedialog_mod.askdirectory = fake.askdirectory  # type: ignore[attr-defined]

    ttk_mod = types.ModuleType("tkinter.ttk")

    tk_mod.simpledialog = simpledialog_mod  # type: ignore[attr-defined]
    tk_mod.messagebox = messagebox_mod  # type: ignore[attr-defined]
    tk_mod.filedialog = filedialog_mod  # type: ignore[attr-defined]
    tk_mod.ttk = ttk_mod  # type: ignore[attr-defined]

    for name, mod in (
        ("tkinter", tk_mod),
        ("tkinter.simpledialog", simpledialog_mod),
        ("tkinter.messagebox", messagebox_mod),
        ("tkinter.filedialog", filedialog_mod),
        ("tkinter.ttk", ttk_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    return fake


@pytest.fixture
def fake_tk(monkeypatch: pytest.MonkeyPatch) -> FakeTkinter:
    """Install a scripted, window-free tkinter and return the recorder."""
    return _install_fake_tkinter(monkeypatch)


@pytest.fixture
def no_tkinter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import tkinter`` raise ImportError, as on a tkinter-less build."""
    for name in (
        "tkinter",
        "tkinter.simpledialog",
        "tkinter.messagebox",
        "tkinter.filedialog",
        "tkinter.ttk",
    ):
        monkeypatch.setitem(sys.modules, name, None)


@pytest.fixture
def no_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if anything tries to read the console.

    This is the guard for agent issue #44: in a GUI app a blocking stdin
    read is an invisible hang, so a cancelled dialog must never reach one.
    """

    def _forbidden(*_args: Any, **_kw: Any) -> str:
        raise AssertionError("stdin was read; the GUI path must not fall back to the console")

    monkeypatch.setattr("builtins.input", _forbidden)
    monkeypatch.setattr("getpass.getpass", _forbidden)
