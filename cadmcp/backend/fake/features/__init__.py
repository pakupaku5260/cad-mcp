"""Fake backend · feature domain（S8e split in phases）。"""
from .extrude import FakeExtrudeMixin
from .manage import FakeFeatureManageMixin
from .revolve import FakeRevolveMixin

__all__ = ["FakeExtrudeMixin", "FakeFeatureManageMixin", "FakeRevolveMixin"]
