"""Single-instance guard backed by a Windows named mutex.

On non-Windows the implementation is a no-op so the module stays
importable for CI. `try_acquire()` always returns True off-Windows;
don't rely on it for cross-platform mutual exclusion.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

MUTEX_NAME = "Global\\DeepAnalysisAgent"

try:  # pragma: no cover — Windows only
    import win32api
    import win32event
    import winerror

    _WIN32 = True
except ImportError:  # pragma: no cover — non-Windows CI path
    win32api = None
    win32event = None
    winerror = None
    _WIN32 = False


class AlreadyRunningError(RuntimeError):
    """Raised when another agent instance already holds the mutex."""


class InstanceLock:
    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle: Any = None

    def try_acquire(self) -> bool:
        if not _WIN32:
            return True
        handle = win32event.CreateMutex(None, False, self._name)
        last_error = win32api.GetLastError()
        if last_error == winerror.ERROR_ALREADY_EXISTS:
            win32api.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is not None and _WIN32:
            win32api.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> InstanceLock:
        if not self.try_acquire():
            raise AlreadyRunningError(f"another instance holds {self._name}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
