"""Protocol layer · CADBackend protocol interface."""
from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from cadmcp.backend.protocol.models import (
    BomRow,
    ComponentRef,
    DimensionRef,
    DocInfo,
    EdgeRef,
    EquationRef,
    FaceRef,
    FeatureInfo,
    FingerprintSI,
    HelixInfo,
    InterferencePair,
    MassPropsSI,
    MateInfo,
    RebuildOutcome,
    SheetMetalFlatSI,
    SketchEntityRef,
    SketchInfo,
    SketchLineRef,
    SketchSolveStatus,
    VertexRef,
)


class CADBackend(Protocol):
    """Behavioral backend protocol. All methods raise CadMcpError on COM failure."""

    # --- Connection/version (doctor and health checks) ---
    def revision(self) -> str:
        """SolidWorks version string, e.g. '33.0' (SW2025)."""
        ...

    # --- Document domain ---
    def new_part(self, template: str | None = None) -> DocInfo: ...

    def new_assembly(self, template: str | None = None) -> DocInfo: ...

    def open_document(self, path: Path) -> DocInfo: ...

    def save_as(self, path: Path) -> None:
        """Save to a sandbox-validated path. Default no-overwrite policy is enforced by the tool gate."""
        ...

    def close_document(self, discard: bool) -> None:
        """Close the active document. Unsaved-change prompts are handled by the tool layer; the backend must not repeat that logic.
        The backend must ensure the document is actually closed on return, or raise CadMcpError."""
        ...

    def active_document(self) -> DocInfo | None: ...

    def list_configurations(self) -> tuple[str, list[str]]:
        """(active configuration name, all configuration names). Parts/assemblies only; drawings raise INVALID_ARGUMENT."""
        ...

    def set_configuration(self, name: str, create: bool = False) -> tuple[str, bool]:
        """Activate a configuration; create if missing when create=True. Returns (name, was_created)."""
        ...

    def get_material(self) -> tuple[str, str]:
        """Part material grade and library name (empty strings if unset)."""
        ...

    def set_material(self, name: str) -> tuple[str, str]:
        """Set material on the active part configuration by grade name."""
        ...

    def new_drawing(self, template: str | None = None) -> DocInfo:
        """Create a drawing (real: NewDrawing2 + .drwdot)."""
        ...

    def create_drawing_view(self, model: Path, view: str) -> str:
        """Create a standard model view on the active drawing. view: front/back/left/right/top/bottom/isometric."""
        ...

    def create_section_view(
        self, label: str = "A", x_m: float = 0.22, y_m: float = 0.15, depth_m: float = 0.0
    ) -> str:
        """Create a section view on an existing model view. Requires create_drawing_view first."""
        ...

    def insert_model_items(self) -> int:
        """Import model dimensions into the current drawing view. Returns dimension count."""
        ...

    def insert_balloons(self) -> int:
        """Auto balloon the current drawing view. Assembly uses item numbers; returns balloon count."""
        ...

    def set_sheet_props(self, paper: str, scale: tuple[float, float]) -> dict:
        """Set drawing sheet size and scale (DRW3 L2)."""
        ...

    def create_detail_view(
        self, label: str = "B", x_m: float = 0.0, y_m: float = 0.0, radius_m: float = 0.01
    ) -> str:
        """Detail view (DRW3 L2). Requires a model view first."""
        ...

    def apply_drawing_tolerances(self, tolerances: list[dict]) -> int:
        """Apply tolerance records to imported dimensions (DRW3 L2). Returns count written."""
        ...

    def inspect_drawing(self) -> dict:
        """Inspect drawing: view count / dimension count / sheet scale / tolerances (DRW3); L3 adds sheets/title_block/gdt."""
        ...

    def add_drawing_sheet(self, name: str, paper: str, scale: tuple[float, float]) -> dict:
        """Add a drawing sheet and set size/scale (DRW3 L3-A)."""
        ...

    def activate_drawing_sheet(self, name: str) -> str:
        """Activate an existing drawing sheet (DRW3 L3-A)."""
        ...

    def list_drawing_sheets(self) -> list[str]:
        """List drawing sheet names (DRW3 L3-A)."""
        ...

    def add_drawing_layer(self, name: str, color: int = 255) -> dict:
        """Drawing layer. color is a SolidWorks color value (default 255=red). DXF export writes the layer table."""
        ...

    def set_drawing_layer(self, name: str) -> str:
        """Set the active layer to an existing name; subsequent annotations use that layer."""
        ...

    def list_drawing_layers(self) -> dict:
        """Layers: count is total; current is active; layers are known this session (including added).
        SW2025 COM has no stable API to enumerate all layer names by index."""
        ...

    def set_title_block(self, props: dict[str, str]) -> dict:
        """Write title block custom properties (DRW3 L3-B). Returns keys written."""
        ...

    def get_title_block(self, keys: list[str] | None = None) -> dict:
        """Read title block properties; default key set when keys omitted (DRW3 L3-B)."""
        ...

    def insert_datum(
        self, label: str, x_m: float = 0.1, y_m: float = 0.1, edge: int | None = None
    ) -> str:
        """Insert datum symbol (DRW3 L3-C). edge is visible edge index; auto-picks first when omitted."""
        ...

    def insert_gdt(
        self,
        symbol: str,
        tolerance: str,
        datums: tuple[str, ...] = (),
        x_m: float = 0.1,
        y_m: float = 0.1,
        edge: int | None = None,
    ) -> str:
        """Insert GD&T frame (DRW3 L3-C). symbol per GDT_SYMBOLS; edge same as insert_datum."""
        ...

    def export_document(
        self,
        path: Path,
        fmt: str,
        *,
        step_ap: int | None = None,
        stl_quality: str | None = None,
    ) -> None:
        """Export the active document to a validated path. fmt: step/stl (part/assembly) or pdf/dxf (drawing).
        Optional step_ap (203/214) and stl_quality (coarse/fine). Export is copy semantics."""
        ...

    def get_bom(self) -> tuple[str, list[BomRow]]:
        """Rolling BOM on assembly/part (item, qty, material, config). Drawing without table: FEATURE_NOT_FOUND; with table: source=drawing."""
        ...

    def insert_bom(self, bom_type: str = "top") -> int:
        """Insert BOM on active drawing. bom_type: parts/top/indented. Returns row count (with header).
        Real path: assembly model view + IView.InsertBomTable6 + absolute .sldbomtbt path."""
        ...

    # --- Sketch domain ---
    def list_planes(self) -> list[str]: ...

    def create_plane(
        self,
        reference: str | None = None,
        offset_m: float = 0.0,
        flip: bool = False,
        *,
        mode: str = "offset",
        angle_rad: float | None = None,
        axis: str | None = None,
        points_m: Sequence[tuple[float, float, float]] | None = None,
    ) -> FeatureInfo:
        """Reference plane. mode=offset (default, reference+offset) / angle (reference+axis+angle) / points (three points)."""
        ...

    def create_axis(
        self, planes: tuple[str, str] | None = None, edge: int | None = None
    ) -> FeatureInfo:
        """Intersection of two planes, or a straight edge from get_edges. Provide one."""
        ...

    def begin_sketch(self, plane: str) -> None: ...

    def end_sketch(self) -> SketchInfo: ...

    def active_sketch(self) -> SketchInfo | None: ...

    def draw_rectangle(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
    ) -> None:
        """Corner rectangle. z1/z2 only for 3D sketches; nonzero z on planar sketch → INVALID_ARGUMENT."""
        ...

    def draw_circle(
        self, cx_m: float, cy_m: float, radius_m: float, cz_m: float = 0.0
    ) -> None:
        """Center circle. cz only for 3D sketches; nonzero cz on planar sketch → INVALID_ARGUMENT."""
        ...

    def sketch_line(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
    ) -> None: ...

    def sketch_arc(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        x3_m: float | None = None,
        y3_m: float | None = None,
        cx_m: float | None = None,
        cy_m: float | None = None,
        ccw: bool = True,
        z1_m: float = 0.0,
        z2_m: float = 0.0,
        z3_m: float = 0.0,
        cz_m: float = 0.0,
    ) -> None:
        """Arc. Three-point: start/on-arc/end; or center+start/end. z*/cz only for 3D (start_sketch plane=3D)."""
        ...

    def sketch_spline(
        self, points_m: list[tuple[float, float, float]], closed: bool = False
    ) -> None:
        """Spline. points_m are (x,y,z) meters; planar sketch z must be 0; 3D may use z. closed closes start/end."""
        ...

    def sketch_polygon(
        self,
        sides: int,
        radius_or_distance: float,
        polygon_type: str = "inscribed",
        cx_m: float = 0.0,
        cy_m: float = 0.0,
        cz_m: float = 0.0,
    ) -> list[SketchLineRef]:
        """Regular polygon. cx/cy/cz is center; cz only for 3D; nonzero cz on planar → INVALID_ARGUMENT."""
        ...

    def add_sketch_dimension(
        self,
        x1_m: float,
        y1_m: float,
        x2_m: float,
        y2_m: float,
        value_m: float,
        entity1: int | None = None,
        entity2: int | None = None,
    ) -> None: ...

    def add_sketch_relation(
        self,
        relation: str,
        entity1: int,
        entity2: int | None = None,
        entity3: int | None = None,
    ) -> None: ...

    def list_sketch_entities(self, sketch: str | None = None) -> list[SketchEntityRef]:
        """List sketch entities. Omit sketch to use the open sketch."""
        ...

    def sketch_offset(self, distance_m: float, inward: bool = False) -> None:
        """Offset the current sketch profile. inward offsets inward (negative); original profile kept as a frame."""
        ...

    def sketch_trim(self, entity1: int, entity2: int, radius_m: float) -> None:
        """Fillet trim at entity intersection (2025 SketchTrim unavailable; uses CreateFillet)."""
        ...

    def sketch_mirror(self, axis: int) -> None:
        """Mirror other entities about a sketch line. That line becomes construction."""
        ...

    def edit_sketch(self, name: str) -> SketchInfo:
        """Edit a ended sketch. Open sketch present → SKETCH_OP_FAILED."""
        ...

    def sketch_solve_status(self, sketch: str | None = None) -> SketchSolveStatus:
        """Under / fully / over defined. Omit sketch to use the open sketch."""
        ...

    # --- Feature domain ---
    def extrude_blind(
        self,
        depth_m: float,
        sketch: str | None = None,
        *,
        direction: str = "blind",
        depth2_m: float | None = None,
        reverse: bool = False,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
        merge: bool = True,
        thin: bool = False,
        thickness_m: float | None = None,
        thin_type: str = "one",
    ) -> FeatureInfo:
        """Extrude. direction includes through_all / up_to_next / up_to_surface (needs end_face) /
        up_to_vertex (needs end_vertex) / up_to_body (needs end_body; creation to-face equivalent, not native Type=7).
        merge=False yields separate bodies. thin uses FeatureExtrusionThin2."""
        ...

    def extrude_cut(
        self,
        depth_m: float,
        sketch: str | None = None,
        *,
        direction: str = "blind",
        depth2_m: float | None = None,
        reverse: bool | None = None,
        end_face: int | None = None,
        end_vertex: int | None = None,
        end_body: int | None = None,
        thin: bool = False,
        thickness_m: float | None = None,
        thin_type: str = "one",
    ) -> FeatureInfo:
        """Extrude cut. reverse=None probes Dir False→True on real SW; requires existing material."""
        ...

    def revolve_blind(
        self,
        angle_rad: float,
        axis: str,
        sketch: str | None = None,
        edge_index: int | None = None,
    ) -> FeatureInfo:
        """Revolve profile. Default model axis through origin; edge_index uses that straight edge."""
        ...

    def fillet_blind(
        self,
        radius_m: float,
        target: str | None = None,
        edge_indexes: Sequence[int] | None = None,
    ) -> FeatureInfo:
        """Fillet. edge_indexes are global from get_edges; else target=feature name or whole part."""
        ...

    def chamfer_blind(
        self,
        distance_m: float,
        target: str | None = None,
        edge_indexes: Sequence[int] | None = None,
        angle_rad: float = math.pi / 4,
    ) -> FeatureInfo:
        """Angle-distance chamfer (default 45°). edge_indexes from get_edges; else target=feature or whole part."""
        ...

    def shell_blind(
        self, thickness_m: float, face_indexes: Sequence[int] | None = None
    ) -> FeatureInfo:
        """Shell. face_indexes are open faces (get_faces indexes); None is closed shell."""
        ...

    def linear_pattern_blind(
        self, feature: str, dx_m: float, dy_m: float, dz_m: float, count: int
    ) -> FeatureInfo:
        """Linear pattern: replicate feature along (dx,dy,dz), count instances including seed (count ≥ 2)."""
        ...

    def circular_pattern_blind(
        self,
        feature: str,
        count: int,
        axis: str,
        edge_index: int | None = None,
    ) -> FeatureInfo:
        """Circular pattern: about model axis (REVOLVE_AXES) or an edge; count includes seed; equal spacing."""
        ...

    def mirror_feature(self, feature: str, plane: str, scope: str = "body") -> FeatureInfo:
        """Mirror about reference plane. scope=body (default; 2025 Right off-body reliable) or feature."""
        ...

    def create_helix(
        self,
        pitch_m: float,
        revolutions: float = 1.0,
        height_m: float | None = None,
        start_angle_rad: float = 0.0,
        clockwise: bool = False,
    ) -> HelixInfo: ...

    def sweep(self, profile_sketch: str | None = None, path_sketch: str | None = None) -> FeatureInfo: ...

    def sweep_cut(self, profile_sketch: str | None = None, path_sketch: str | None = None) -> FeatureInfo: ...

    def loft(
        self,
        profiles: Sequence[str] | None = None,
        *,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        """Solid loft. profiles are ended sketch names (≥2); omit for latest two.
        guides are open-curve sketches through sections; empty means none.
        centerline is one open-curve sketch (line mark=4); cannot combine with guides."""
        ...

    def loft_cut(
        self,
        profiles: Sequence[str] | None = None,
        *,
        guides: Sequence[str] | None = None,
        centerline: str | None = None,
    ) -> FeatureInfo:
        """Loft cut. Requires existing solid. guides/centerline same as loft."""
        ...

    def extrude_surface(self, depth_m: float, sketch: str | None = None) -> FeatureInfo:
        """Extrude ended sketch to surface (not solid). Omit sketch for latest ended sketch."""
        ...

    def knit(self, surfaces: Sequence[str] | None = None) -> FeatureInfo:
        """Knit surface sheets. surfaces are surface feature/sheet names; omit for latest two sheets."""
        ...

    def thicken(self, thickness_m: float, surface: str | None = None) -> FeatureInfo:
        """Thicken surface to solid. Open knitted sheets fail. Omit surface for latest surface."""
        ...

    def fill_surface(self, surface: str | None = None, edge: int = 0) -> FeatureInfo:
        """Fill surface from sheet edge (InsertFillSurface2). Omit surface for latest sheet."""
        ...

    def boundary_surface(
        self, profiles: Sequence[str] | None = None
    ) -> FeatureInfo:
        """Boundary surface from two profiles (InsertLoftRefSurface2). Omit profiles for latest two ended sketches."""
        ...

    def trim_surface(
        self,
        tool: str | None = None,
        target: str | None = None,
        keep: int = 0,
    ) -> FeatureInfo:
        """Trim target with tool sheet; keep is GetPreTrimmedBodies piece index. Omit for latest two surfaces in tree."""
        ...

    def extend_surface(
        self,
        distance_m: float,
        surface: str | None = None,
        edge: int | None = None,
        linear: bool = True,
    ) -> FeatureInfo:
        """Extend sheet by distance. Omit surface for latest; omit edge for first face else that edge index."""
        ...

    def fillet_surface(
        self, radius_m: float, surface: str | None = None, edge: int = 0
    ) -> FeatureInfo:
        """Fillet sheet edges (FeatureFillet3). Omit surface for latest sheet."""
        ...

    def untrim_surface(self, surface: str | None = None) -> FeatureInfo:
        """Untrim (InsertUntrimSurface). Omit surface for latest sheet;
        default AllEdges + ConnectEndPoints."""
        ...

    def rib(self, thickness_m: float, sketch: str | None = None) -> FeatureInfo:
        """Rib. Ended sketch must be a line; 2025 InsertRib returns None, uses thin extrude."""
        ...

    def draft(
        self, angle_rad: float, faces: Sequence[int], neutral: int, flip: bool = False
    ) -> FeatureInfo:
        """Draft with neutral plane. faces/neutral are get_faces indexes."""
        ...

    def combine(self, op: str, keep: int = 0) -> FeatureInfo:
        """Combine bodies: add / cut / common. cut keep is kept body index."""
        ...

    def split_body(self, plane: str) -> FeatureInfo:
        """Split body with reference plane. plane is Front/Top/Right or list_planes name."""
        ...

    def parting_line(
        self,
        pull_face: int,
        edges: Sequence[int] | None = None,
        *,
        flip: bool = False,
    ) -> FeatureInfo:
        """Mold parting line. pull_face is get_faces index (pull direction); edges from get_edges;
        omit for all edges (box probe). flip reverses pull."""
        ...

    def parting_surface(
        self,
        parting_line: str | None = None,
        *,
        radiate: bool = False,
        offset_m: float = 0.0,
        knit: bool = False,
    ) -> FeatureInfo:
        """Mold parting surface. Omit parting_line for latest MoldPartingLine.
        radiate=True radiates by offset_m; knit stitches result sheets."""
        ...

    def shut_off_surface(self, edges: Sequence[int] | None = None) -> FeatureInfo:
        """Mold shut-off surface. Requires parting_line; edges from get_edges;
        omit for all edges (box probe). Return marshaling often fails—trust feature tree."""
        ...

    def hole_wizard(
        self,
        face: int,
        diameter_m: float,
        end: str = "blind",
        depth_m: float | None = None,
        x_m: float | None = None,
        y_m: float | None = None,
    ) -> FeatureInfo:
        """ISO hole wizard. face is get_faces index; through_all needs no depth."""
        ...

    def base_flange(
        self,
        thickness_m: float,
        radius_m: float | None = None,
        sketch: str | None = None,
    ) -> FeatureInfo:
        """Closed-sketch base flange. radius defaults to 0.5×thickness."""
        ...

    def edge_flange(
        self,
        edge: int,
        length_m: float,
        angle_rad: float = math.pi / 2,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        """Edge flange. edge is get_edges index. Requires base flange."""
        ...

    def sheet_metal_unfold(self) -> SheetMetalFlatSI:
        """Unsuppress flat pattern; returns flat outline and K-factor."""
        ...

    def miter_flange(
        self,
        edges: list[int],
        length_m: float,
        angle_rad: float = math.pi / 2,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        """Miter flange (SM2). edges is get_edges index list."""
        ...

    def hem_flange(
        self,
        edge: int,
        length_m: float,
        radius_m: float | None = None,
    ) -> FeatureInfo:
        """Hem (SM2). edge is get_edges index."""
        ...

    def export_flat_dxf(self, path: Path) -> None:
        """Export flat pattern DXF (SM2; ExportToDWG2)."""
        ...

    def sheet_metal_bend_table(self) -> list[dict]:
        """Read bend table (SM2). Empty list when no table."""
        ...

    def insert_thread(
        self,
        diameter_m: float,
        pitch_m: float,
        length_m: float | None = None,
        internal: bool = False,
    ) -> FeatureInfo: ...

    def delete_feature(self, name: str) -> None: ...

    def suppress_feature(self, name: str, suppress: bool = True) -> FeatureInfo: ...

    def force_rebuild(self) -> RebuildOutcome: ...

    # --- Assembly domain ---
    def insert_component(self, path: Path, x_m: float = 0.0, y_m: float = 0.0, z_m: float = 0.0) -> ComponentRef: ...

    def move_component(
        self,
        name: str,
        x_m: float,
        y_m: float,
        z_m: float,
        relative: bool = False,
        force: bool = False,
    ) -> ComponentRef:
        """Place component origin at assembly (x,y,z); relative for delta. Mated: fail by default; force still writes."""
        ...

    def rotate_component(
        self,
        name: str,
        axis: str,
        angle_rad: float,
        about: str = "origin",
        absolute: bool = False,
        force: bool = False,
        pivot_m: tuple[float, float, float] | None = None,
    ) -> ComponentRef:
        """Rotate about model axis. absolute from identity; pivot_m overrides about. Mated: fail by default."""
        ...

    def list_components(self, children: bool = False) -> list[ComponentRef]:
        """Components in active assembly (name, path, **solved** origin/bbox).

        Top level by default. children=True includes subassembly instances as ``p1-1@sub-1``.
        """
        ...

    def get_component(self, name: str) -> ComponentRef:
        """Get **mate-solved** pose by instance name. Not found → INVALID_ARGUMENT."""
        ...

    def set_lightweight(self, name: str, lightweight: bool) -> str:
        """Lightweight or fully resolve component. Returns instance name. Suppressed not implemented."""
        ...

    def explode_view(self) -> tuple[str, list[str]]:
        """Create explode view. Returns (name, all names). Screw mates not implemented."""
        ...

    def show_exploded(self, show: bool, name: str | None = None) -> tuple[str | None, list[str], bool]:
        """Show or collapse explode view. Uses current/latest when name omitted."""
        ...

    def list_exploded_views(self) -> tuple[list[str], bool]:
        """Explode view names and whether explode display is active."""
        ...

    def pattern_component(
        self,
        name: str,
        count: int,
        axis: str | None = None,
        about: str = "world",
        dx_m: float | None = None,
        dy_m: float | None = None,
        dz_m: float | None = None,
    ) -> tuple[FeatureInfo, list[ComponentRef]]:
        """Circular or linear component pattern. count includes seed, ≥2. Deleting feature removes copies, keeps seed.
        Circular: axis; linear: one of dx/dy/dz (single axis)."""
        ...

    def edit_component(self, name: str) -> str:
        """Edit subassembly in context. Returns current edit target component name."""
        ...

    def end_edit(self) -> None:
        """Exit in-context edit; return to top assembly."""
        ...

    def get_edit_target(self) -> str | None:
        """In-context edit target component name; None at top level."""
        ...

    def set_color(self, r: float, g: float, b: float) -> tuple[float, float, float]:
        """Part appearance RGB (0–1). Assembly/drawing → INVALID_ARGUMENT."""
        ...

    def get_color(self) -> tuple[float, float, float] | None:
        """Part appearance RGB; None when unset."""
        ...

    def mate_concentric(self, entity1: str, entity2: str, align: str | None = None) -> MateInfo:
        """Concentric: after mate, floating axis coincident with fixed (sliding along axis allowed)."""
        ...

    def mate_coincident(self, entity1: str, entity2: str, align: str | None = None) -> MateInfo:
        """Coincident: after mate, float flush along plane normal; get_component reads solved pose."""
        ...

    def mate_distance(
        self, entity1: str, entity2: str, distance_m: float, align: str | None = None
    ) -> MateInfo: ...

    def mate_angle(
        self, entity1: str, entity2: str, angle_rad: float, align: str | None = None
    ) -> MateInfo: ...

    def mate_tangent(self, entity1: str, entity2: str, align: str | None = None) -> MateInfo: ...

    def mate_screw(
        self, entity1: str, entity2: str, pitch_m: float, align: str | None = None
    ) -> MateInfo: ...

    def list_mates(self) -> list[MateInfo]:
        """Mate list in active assembly (name + type)."""
        ...

    def delete_mate(self, name: str) -> None:
        """Delete mate by name; not found → FEATURE_NOT_FOUND."""
        ...

    def list_component_faces(self, component: str, kind: str | None = None) -> list[FaceRef]:
        """Face list for a component (index from 0, for p1-1#face:N).
        kind filter returns that geometry only; index remains global face order."""
        ...

    def list_component_edges(self, component: str, kind: str | None = None) -> list[EdgeRef]:
        """Edge list for a component (index from 0, for p1-1#edge:N).
        kind filter returns that geometry only; index remains global edge order."""
        ...

    def check_interference(
        self,
        component1: str | None = None,
        component2: str | None = None,
        coincident_as_interference: bool = False,
    ) -> tuple[list[InterferencePair], str]:
        """Assembly interference: returns (non-clear pairs, method name aabb|solidworks)."""
        ...

    def select_face(self, index: int) -> None: ...

    def select_edge(self, index: int) -> None: ...

    def get_faces(self, kind: str | None = None, query: str | None = None) -> list[FaceRef]:
        """Part face list. kind filters; query is extrema like max_z or cylinder axis like axis_z."""
        ...

    def get_edges(self) -> list[EdgeRef]: ...

    def get_vertices(self) -> list[VertexRef]:
        """Part vertex list (globally ordered index; for up_to_vertex end_vertex)."""
        ...

    # --- Query domain (reads; does not bump kernel state_version) ---
    def mass_properties(self) -> MassPropsSI: ...

    def fingerprint(self) -> FingerprintSI: ...

    def list_features(self) -> list[FeatureInfo]: ...

    def list_dimensions(self) -> list[DimensionRef]:
        """Dimensions on active part (feature and sketch short names). Assembly/drawing → INVALID_ARGUMENT."""
        ...

    def set_dimension(self, name: str, value_si: float) -> DimensionRef:
        """Set dimension by short name (length meters / angle radians). Missing → FEATURE_NOT_FOUND."""
        ...

    def list_equations(self) -> list[EquationRef]:
        """Part equations (globals and dimension-driven). Assembly/drawing → INVALID_ARGUMENT."""
        ...

    def set_equation(self, name: str, expression: str) -> EquationRef:
        """Write or replace equation. RHS only numbers and arithmetic on existing names."""
        ...

    def list_faces(self) -> list[FaceRef]:
        """All face bodies (index globally ordered per list; selector candidate pool)."""
        ...

    def list_edges(self) -> list[EdgeRef]:
        """All edge bodies (index globally ordered per list; selector candidate pool)."""
        ...

    def list_vertices(self) -> list[VertexRef]:
        """All vertices (index globally ordered)."""
        ...

    def selected_entities(self) -> list[FaceRef | EdgeRef]:
        """GUI-picked entities (get_selection fallback); empty list when none selected."""
        ...

    # --- View domain ---
    def set_view(self, view: str) -> None: ...

    def screenshot(self, path: Path, view: str) -> None:
        """Save image to sandbox-validated path; file exists means success (return value unreliable across versions)."""
        ...
