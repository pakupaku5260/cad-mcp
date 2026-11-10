"""Fake backend (in-memory simulation). S8 split across _state / _calls / _engine / domains / backend.

S8a: _state.py + _calls.py (dataclasses + call log).
S8b~h：_engine.py / domains Mixin / backend.py。
S8i: fake_backend.py becomes a shim.
"""
from .backend import FakeBackend

__all__ = ["FakeBackend"]
