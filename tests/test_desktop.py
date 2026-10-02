import builtins
import sys

import pytest

from batterylog import desktop


def test_help_does_not_import_gui(monkeypatch, capsys):
    original = builtins.__import__

    def no_gui(name, *args, **kwargs):
        if name in {"desktop_ui", "tkinter"}:
            pytest.fail("Help must not require a GUI installation")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_gui)
    with pytest.raises(SystemExit) as exc:
        desktop.run(["--help"])
    assert exc.value.code == 0
    assert "desktop launcher" in capsys.readouterr().out


def test_missing_tk_has_actionable_error(monkeypatch, capsys):
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "desktop_ui":
            raise ImportError("No module named tkinter")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    assert desktop.run([]) == 4
    assert "Tkinter/Tcl/Tk" in capsys.readouterr().err


def test_entry_point_propagates_gui_exit(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "batterylog.desktop_ui", SimpleNamespace(launch=lambda: 0))
    monkeypatch.setattr(sys, "argv", ["batterylog-gui"])
    with pytest.raises(SystemExit) as exc:
        desktop.main()
    assert exc.value.code == 0
