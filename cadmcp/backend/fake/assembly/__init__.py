"""Fake backend · assembly domain (S8f onward split in phases)."""
from .explode import FakeAssemblyExplodeMixin
from .query import FakeAssemblyQueryMixin

__all__ = ["FakeAssemblyExplodeMixin", "FakeAssemblyQueryMixin"]
