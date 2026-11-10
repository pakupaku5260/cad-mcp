"""Shared fixtures: core registry, fake backend, kernel (per-test isolated temp workspace)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cadmcp.backend.fake.backend import FakeBackend
from cadmcp.kernel import Kernel
from cadmcp.toolsets.core import core_registry


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch, tmp_path: Path) -> None:
    """Point user config dirs at tmp_path so tokens/audit never touch real %APPDATA% or ~/.config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def fake() -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def kernel(workspace: Path, fake: FakeBackend) -> Kernel:
    return Kernel(core_registry(), fake, workspace=workspace)


@pytest.fixture()
def make_kernel(workspace: Path):
    """Build a kernel with optional fault injection: make_kernel(fail_on=[("extrude_blind", 1)])."""

    def _make(*, fake: FakeBackend | None = None, **kwargs) -> Kernel:
        backend = fake or FakeBackend(**kwargs)
        return Kernel(core_registry(), backend, workspace=workspace)

    return _make
