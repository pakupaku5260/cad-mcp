"""COM backend: ComBackend composite class.

S2: infrastructure (STAThreadMixin + COMConnectionMixin + InfrastructureMixin).
S3: + NamingMixin / SelectionMixin / GeometryMixin.
S4: + SketchMixin / DocumentMixin / DrawingMixin / PlaneAxisMixin / ConfigMixin / ViewMixin.
S5: + ExtrudeMixin / RevolveMixin / ModifyMixin / PatternMixin / SurfaceMixin / HelixMixin / SheetMetalMixin.

Warning: Coexists with `com_backend.ComBackend` during S5.
Warning: Switch to this class only after S6 completes.
"""
from __future__ import annotations

from cadmcp.backend.solidworks.assembly.explode import ExplodeMixin
from cadmcp.backend.solidworks.assembly.mate import MateMixin
from cadmcp.backend.solidworks.config import ConfigMixin
from cadmcp.backend.solidworks.dimension import DimensionMixin
from cadmcp.backend.solidworks.document import DocumentMixin
from cadmcp.backend.solidworks.drawing import DrawingMixin
from cadmcp.backend.solidworks.features.extrude import ExtrudeMixin
from cadmcp.backend.solidworks.features.helix import HelixMixin
from cadmcp.backend.solidworks.features.modify import ModifyMixin
from cadmcp.backend.solidworks.features.pattern import PatternMixin
from cadmcp.backend.solidworks.features.revolve import RevolveMixin
from cadmcp.backend.solidworks.features.sheetmetal import SheetMetalMixin
from cadmcp.backend.solidworks.features.surface import SurfaceMixin
from cadmcp.backend.solidworks.geometry import GeometryMixin
from cadmcp.backend.solidworks.infrastructure import COMConnectionMixin, InfrastructureMixin
from cadmcp.backend.solidworks.naming import NamingMixin
from cadmcp.backend.solidworks.plane_axis import PlaneAxisMixin
from cadmcp.backend.solidworks.query import QueryMixin
from cadmcp.backend.solidworks.selection import SelectionMixin
from cadmcp.backend.solidworks.sketch import SketchMixin
from cadmcp.backend.solidworks.sta import STAThreadMixin
from cadmcp.backend.solidworks.view import ViewMixin

from .assembly.component import ComponentMixin


class ComBackend(
    ComponentMixin,
    MateMixin,
    ExplodeMixin,
    STAThreadMixin,
    COMConnectionMixin,
    InfrastructureMixin,
    NamingMixin,
    SelectionMixin,
    GeometryMixin,
    QueryMixin,
    SketchMixin,
    DocumentMixin,
    DrawingMixin,
    PlaneAxisMixin,
    ConfigMixin,
    DimensionMixin,
    ViewMixin,
    ExtrudeMixin,
    RevolveMixin,
    ModifyMixin,
    PatternMixin,
    SurfaceMixin,
    HelixMixin,
    SheetMetalMixin,
):
    """Real COM backend (S5: infrastructure + 9 business domains + 7 feature domains)."""

    MODELING_DOMAIN_READY = True

    def __init__(self) -> None:
        ComponentMixin._init_state(self)
        MateMixin._init_state(self)
        ExplodeMixin._init_state(self)
        STAThreadMixin._init_state(self)
        COMConnectionMixin._init_state(self)
        InfrastructureMixin._init_state(self)
        NamingMixin._init_state(self)
        SelectionMixin._init_state(self)
        GeometryMixin._init_state(self)
        QueryMixin._init_state(self)
        SketchMixin._init_state(self)
        DocumentMixin._init_state(self)
        DrawingMixin._init_state(self)
        PlaneAxisMixin._init_state(self)
        ConfigMixin._init_state(self)
        DimensionMixin._init_state(self)
        ViewMixin._init_state(self)
        ExtrudeMixin._init_state(self)
        RevolveMixin._init_state(self)
        ModifyMixin._init_state(self)
        PatternMixin._init_state(self)
        SurfaceMixin._init_state(self)
        HelixMixin._init_state(self)
        SheetMetalMixin._init_state(self)


__all__ = ["ComBackend"]
