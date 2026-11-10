"""Fake backend · feature domain · feature management（S8e-2）。

S8e-2：delete_feature / suppress_feature / force_rebuild。

Dependencies (self, MRO):
- `_enter` / `_require_doc`（FakeBackend）
- `_apply_equations` (FakeQueryMixin; on FakeBackend until S8e-3)
- `_drop_component` (FakeAssemblyComponentMixin; on FakeBackend until S8f)

Imports:
- `cadmcp.backend.protocol.models`（FeatureInfo / RebuildOutcome）
- `cadmcp.errors`（fail）
"""
from __future__ import annotations

from cadmcp.backend.protocol.models import FeatureInfo, RebuildOutcome
from cadmcp.errors import fail


class FakeFeatureManageMixin:
    """feature management (S8e-2: 3 methods)."""

    def _init_state(self) -> None:
        pass  # State owned by FakeBackend._init_state

    def delete_feature(self, name: str) -> None:
        self._enter("delete_feature", name=name)
        doc = self._require_doc()
        hit = next((f for f in doc.features if f.get("name") == name), None)
        if hit is None:
            raise fail("FEATURE_NOT_FOUND", f"Feature not found: {name!r}", "Use list_features to list feature names")
        for copy in list(hit.get("copies") or []):
            self._drop_component(doc, copy)
        doc.features = [f for f in doc.features if f.get("name") != name]
        doc.dimensions = {
            k: v for k, v in doc.dimensions.items() if v.get("owner") != name
        }
        doc.modified = True

    def suppress_feature(self, name: str, suppress: bool = True) -> FeatureInfo:
        self._enter("suppress_feature", feature=name, suppress=suppress)
        doc = self._require_doc()
        for f in doc.features:
            if f.get("name") == name:
                return FeatureInfo(name=f["name"], kind=f["kind"])
        raise fail("FEATURE_NOT_FOUND", f"Feature not found: {name!r}", "Use list_features to list feature names")

    def force_rebuild(self) -> RebuildOutcome:
        self._enter("force_rebuild")
        doc = self._require_doc()
        if doc.doc_type == "part":
            self._apply_equations(doc)
        if self._rebuild_errors:
            return RebuildOutcome(ok=False, feature_errors=list(self._rebuild_errors))
        return RebuildOutcome(ok=True)
        