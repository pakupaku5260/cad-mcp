"""Protocol layer · data models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DocInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    path: str | None = None
    doc_type: str = "part"
    modified: bool = False
    units: str = "mm"


class SketchInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plane: str
    entity_count: int
    name: str | None = None


class SketchLineRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    x0_m: float
    y0_m: float
    x1_m: float
    y1_m: float


class SketchEntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    kind: str
    points_m: tuple[tuple[float, float], ...]
    radius_m: float | None = None
    construction: bool = False


class SketchSolveStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["under_defined", "fully_defined", "over_defined"]
    dof: int | None = None


class ComponentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    path: str | None = None
    origin_m: tuple[float, float, float] | None = None
    bbox_m: tuple[float, float, float, float, float, float] | None = None
    lightweight: bool = False


class MateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    mate_type: str
    sw_error: int | None = None
    components: tuple[str, str] | None = None


class BomRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: int
    part_number: str
    qty: int
    material: str = ""
    configuration: str = ""
    path: str | None = None
    components: list[str] = []


class InterferencePair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    status: str
    volume_m3: float | None = None


class HelixInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class DimensionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value_si: float
    kind: str = "length"


class EquationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    expression: str


class FeatureInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str


class SheetMetalFlatSI(BaseModel):
    model_config = ConfigDict(extra="forbid")
    length_m: float
    width_m: float
    thickness_m: float
    k_factor: float


class FaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    kind: str
    centroid_m: tuple[float, float, float]
    normal_m: tuple[float, float, float] | None = None
    axis_m: tuple[float, float, float] | None = None


class EdgeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    kind: str
    midpoint_m: tuple[float, float, float]


class VertexRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    position_m: tuple[float, float, float]


class MassPropsSI(BaseModel):
    model_config = ConfigDict(extra="forbid")
    volume_m3: float
    surface_area_m2: float
    mass_kg: float
    center_of_mass_m: tuple[float, float, float]


class FingerprintSI(BaseModel):
    model_config = ConfigDict(extra="forbid")
    volume_m3: float
    surface_area_m2: float
    mass_kg: float
    face_count: int
    edge_count: int
    bbox_m: tuple[float, float, float, float, float, float]


class RebuildOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    feature_errors: list[str] = []


@dataclass(frozen=True, slots=True)
class MateRef:
    kind: Literal["plane", "face", "edge"]
    component: str
    plane: str | None = None
    face_index: int | None = None
    edge_index: int | None = None
    coord_m: tuple[float, float, float] | None = None
    filter_kind: str | None = None
    