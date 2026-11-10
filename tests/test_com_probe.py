"""W8 row 1: Win32DialogProbe stub — PID/visibility, modal derive, per-window tolerance, PID cache."""

from __future__ import annotations

import sys
import types

import pytest

from cadmcp.backend.solidworks._constants import SW_MAIN_WINDOW_CLASS
from cadmcp.backend.solidworks._helpers import _derive_modal
from cadmcp.backend.solidworks.probe import Win32DialogProbe
from cadmcp.probe import derive_blocker


class _FakeWin32:
    """win32gui stub; FindWindow count checks PID cache."""

    GW_OWNER = 4

    def __init__(self, windows: dict[int, dict], find_result: int = 0) -> None:
        self.windows = windows
        self.find_result = find_result
        self.find_calls = 0

    def EnumWindows(self, cb, extra):  # noqa: N802 — stub mirrors win32 API
        for hwnd in list(self.windows):
            cb(hwnd, extra)

    def IsWindowVisible(self, hwnd):  # noqa: N802
        return self.windows[hwnd]["visible"]

    def IsWindowEnabled(self, hwnd):  # noqa: N802
        w = self.windows[hwnd]
        if w.get("boom_enabled"):
            raise RuntimeError("cannot read owner state")
        return w["enabled"]

    def GetWindowText(self, hwnd):  # noqa: N802
        return self.windows[hwnd]["title"]

    def GetClassName(self, hwnd):  # noqa: N802
        w = self.windows[hwnd]
        if w.get("boom"):
            raise RuntimeError("bad hwnd")
        return w["cls"]

    def GetWindow(self, hwnd, what):  # noqa: N802
        return self.windows[hwnd]["owner"] if what == self.GW_OWNER else 0

    def GetWindowRect(self, hwnd):  # noqa: N802
        return self.windows[hwnd]["rect"]

    def GetWindowThreadProcessId(self, hwnd):  # noqa: N802
        return (7, self.windows[hwnd]["pid"])

    def FindWindow(self, cls, title):  # noqa: N802
        self.find_calls += 1
        assert cls == SW_MAIN_WINDOW_CLASS
        return self.find_result


def _w(pid: int, cls: str = "SWFrame", **over) -> dict:
    base = {
        "pid": pid,
        "cls": cls,
        "title": "",
        "visible": True,
        "enabled": True,
        "owner": 0,
        "rect": (0, 0, 800, 600),
    }
    base.update(over)
    return base


@pytest.fixture
def fake_win32(monkeypatch):
    """Inject win32gui stub; win32process None → win32gui fallback."""

    def install(windows: dict[int, dict], find_result: int = 0) -> _FakeWin32:
        fake = _FakeWin32(windows, find_result)
        monkeypatch.setitem(sys.modules, "win32gui", fake)
        monkeypatch.setitem(sys.modules, "win32process", None)
        monkeypatch.setitem(sys.modules, "win32con", types.SimpleNamespace(GW_OWNER=4))
        return fake

    return install


def test_scan_filters_pid_and_invisible(fake_win32):
    fake_win32(
        {
            0x100: _w(100, cls="SWFrame", title="SolidWorks", enabled=False),  # modal: owner disabled
            0x200: _w(100, cls="#32770", title="另存为", owner=0x100),
            0x300: _w(777, cls="Notepad", title="记事本"),  # other process
            0x400: _w(100, cls="SWHidden", title="", visible=False),  # hidden top-level
        },
        find_result=0x100,
    )
    got = Win32DialogProbe().scan()

    assert {w.title for w in got} == {"SolidWorks", "另存为"}
    by_title = {w.title: w for w in got}
    assert by_title["另存为"].modal is True  # owner disabled → modal
    assert by_title["SolidWorks"].modal is False  # no owner → non-modal
    assert by_title["另存为"].class_name == "#32770"
    assert by_title["SolidWorks"].rect == (0, 0, 800, 600)
    assert derive_blocker(got, None) is True  # row-3 blocker source


def test_scan_resolves_pid_once_then_caches(fake_win32):
    fake = fake_win32({0x100: _w(100, title="SolidWorks")}, find_result=0x100)
    probe = Win32DialogProbe()
    probe.scan()
    probe.scan()
    assert fake.find_calls == 1  # cached after first FindWindow
    assert probe._pid == 100


def test_scan_without_sw_window_raises(fake_win32):
    fake_win32({0x300: _w(777, title="别的")}, find_result=0)
    with pytest.raises(RuntimeError, match="SWFrame"):  # carries calibration ①
        Win32DialogProbe().scan()


def test_scan_falls_back_to_title_for_dynamic_class(fake_win32):
    fake_win32(
        {
            0x500: _w(
                4242,
                cls="Afx:0000000140000000:8:0000000000010003",
                title="SOLIDWORKS 2025 SP0.0 - [零件1 *]",
            )
        },
        find_result=0,
    )
    got = Win32DialogProbe().scan()
    assert [w.title for w in got] == ["SOLIDWORKS 2025 SP0.0 - [零件1 *]"]


def test_scan_missing_win32gui_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32gui", None)  # None in sys.modules → ImportError
    with pytest.raises(RuntimeError, match="win32gui unavailable"):
        Win32DialogProbe().scan()


def test_scan_skips_bad_window(fake_win32):
    fake_win32(
        {
            0x10: _w(100, title="正常"),
            0x20: _w(100, title="坏窗", boom=True),
            0x30: _w(100, title="也好"),
        },
        find_result=0x10,
    )
    got = Win32DialogProbe().scan()
    assert [w.title for w in got] == ["正常", "也好"]  # bad hwnd skipped


def test_scan_owner_state_unreadable_is_unknown(fake_win32):
    fake_win32(
        {
            0x100: _w(100, title="SolidWorks", boom_enabled=True),
            0x200: _w(100, cls="#32770", title="弹窗", owner=0x100),
        },
        find_result=0x100,
    )
    got = Win32DialogProbe().scan()
    dialog = next(w for w in got if w.title == "弹窗")
    assert dialog.modal is None  # owner unreadable → unknown


def test_derive_modal_rules_v1():
    assert _derive_modal(None, None) is False  # no owner: main/float
    assert _derive_modal(0x10, True) is False  # owner enabled: floater
    assert _derive_modal(0x10, False) is True  # owner disabled: modal
    assert _derive_modal(0x10, None) is None  # missing signal → unknown


def test_derive_blocker_three_states():
    from cadmcp.probe import WindowInfo

    def _wi(modal):
        return WindowInfo(title="t", class_name="c", rect=(0, 0, 0, 0), modal=modal)

    assert derive_blocker(None, None) is None  # no probe
    assert derive_blocker(None, "timeout") is None  # probe failed
    assert derive_blocker([], None) is False  # scan ok, no windows
    assert derive_blocker([_wi(False), _wi(None)], None) is False  # no definite modal
    assert derive_blocker([_wi(False), _wi(True)], None) is True
