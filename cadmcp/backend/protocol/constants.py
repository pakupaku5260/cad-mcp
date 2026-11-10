"""Protocol layer · constants and enumerations."""
from __future__ import annotations

STANDARD_VIEWS: tuple[str, ...] = (
    "front", "back", "left", "right", "top", "bottom",
    "isometric", "trimetric", "dimetric",
)

DRAWING_VIEW_ALIASES: dict[str, tuple[str, ...]] = {
    "front": ("*Front", "*前视"),
    "back": ("*Back", "*后视"),
    "left": ("*Left", "*左视"),
    "right": ("*Right", "*右视"),
    "top": ("*Top", "*上视"),
    "bottom": ("*Bottom", "*下视"),
    "isometric": ("*Isometric", "*等轴测"),
    "trimetric": ("*Trimetric", "*三等轴测"),
    "dimetric": ("*Dimetric", "*二等轴测"),
}

BOM_TYPES: tuple[str, ...] = ("parts", "top", "indented")
BOM_TYPE_IDS: dict[str, int] = {"parts": 1, "top": 2, "indented": 3}

# DRW3 L3: default title-block keys + GD&T v1 symbols (live COM frame strings may be probe-corrected)
TITLE_BLOCK_DEFAULT_KEYS: tuple[str, ...] = (
    "PartNo",
    "Description",
    "DrawnBy",
    "Date",
    "Material",
    "Revision",
    "Title",
)
GDT_SYMBOLS: tuple[str, ...] = (
    "position",
    "flatness",
    "perpendicularity",
    "concentricity",
)
# SolidWorks IGtol feature-control frame strings (common forms; probe may correct)
GDT_FRAME_SYMBOLS: dict[str, str] = {
    "position": "<POS>",
    "flatness": "<FLAT>",
    "perpendicularity": "<PERP>",
    "concentricity": "<CONC>",
}
DRAWING_PAPER_CODES: dict[str, int] = {
    "A0": 8,
    "A1": 9,
    "A2": 10,
    "A3": 11,
    "A4": 12,
}

DEFAULT_PLANES: tuple[str, ...] = ("Front Plane", "Top Plane", "Right Plane")
REVOLVE_AXES: tuple[str, ...] = ("+x", "-x", "+y", "-y", "+z", "-z")
POSE_PIVOTS: tuple[str, ...] = ("origin", "world")
MAT_IDENTITY: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)

EXTRUDE_DIRECTIONS: tuple[str, ...] = (
    "blind", "midplane", "both", "through_all", "up_to_next", "up_to_surface",
    "up_to_vertex", "up_to_body",
)
EXTRUDE_DEPTHLESS: frozenset[str] = frozenset(
    {"through_all", "up_to_next", "up_to_surface", "up_to_vertex", "up_to_body"}
)
COMBINE_OPS: tuple[str, ...] = ("add", "cut", "common")
HOLE_WIZARD_ENDS: tuple[str, ...] = ("blind", "through_all")
SW_COMBINE_ADD = 15903
SW_COMBINE_CUT = 15902
SW_COMBINE_COMMON = 15901
SW_COMBINE_OP: dict[str, int] = {
    "add": SW_COMBINE_ADD, "cut": SW_COMBINE_CUT, "common": SW_COMBINE_COMMON,
}
SW_END_BLIND = 0
SW_END_THROUGH_ALL = 1
SW_END_UP_TO_NEXT = 2
SW_END_UP_TO_VERTEX = 3
SW_END_UP_TO_SURFACE = 4
SW_END_MIDPLANE = 6

THIN_TYPES: tuple[str, ...] = ("one", "mid", "both")
SW_THIN_ONE = 0
SW_THIN_OPP = 1
SW_THIN_MID = 2
THIN_BLOCKED_DIRECTIONS: frozenset[str] = frozenset(
    {"up_to_next", "up_to_surface", "up_to_vertex", "up_to_body"}
)

SW_SKETCH_SPLINE = 3

PLANE_ALIASES: dict[str, tuple[str, ...]] = {
    "Front Plane": ("前视基准面", "Front Plane", "前基准面"),
    "Top Plane": ("上视基准面", "Top Plane", "上基准面"),
    "Right Plane": ("右视基准面", "Right Plane", "右基准面"),
}

_3D_SKETCH_PLANE_KEYS = frozenset({"3d", "3dsketch", "3dsk", "3d草图", "三维草图"})

MIRROR_SCOPES: tuple[str, ...] = ("body", "feature")
PLANE_MODES: tuple[str, ...] = ("offset", "angle", "points")
PLANE_ANGLE_AXIS_PLANES: dict[str, tuple[str, str]] = {
    "+x": ("Top Plane", "Front Plane"),
    "-x": ("Top Plane", "Front Plane"),
    "+y": ("Front Plane", "Right Plane"),
    "-y": ("Front Plane", "Right Plane"),
    "+z": ("Right Plane", "Top Plane"),
    "-z": ("Right Plane", "Top Plane"),
}
DEFAULT_PLANE_FRAMES: dict[str, tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]] = {
    "Front Plane": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "Top Plane": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "Right Plane": ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
}

MATE_TYPES = ("concentric", "coincident", "distance", "angle", "tangent", "screw")
_MATE_REF_HINT = (
    "Reference plane as '<plane>@<component instance>', e.g. 'Top Plane@p1-1'; "
    "face as '<component>#face:<index>', optionally with coordinates "
    "'<component>#face:<index>:<x>,<y>,<z>'"
)
MATE_ALIGNS: dict[str, int] = {
    "aligned": 0,
    "anti_aligned": 1,
    "closest": 2,
}
_CLOSEST_DEFAULT_MATES = frozenset({"coincident", "concentric", "tangent"})
_MATE_ENTITY_NEED = {
    "concentric": "Concentric mate needs two cylindrical faces (#cylinder:0) or two circular edges (#circle:0)",
    "screw": "Screw mate needs two cylindrical faces or two circular edges",
    "coincident": "Coincident mate needs two planes (#plane:0 or Top Plane@instance)",
    "distance": "Distance mate needs two planes",
    "angle": "Angle mate needs two planes",
    "tangent": "Tangent mate needs faces suitable for tangency",
}

SKETCH_RELATIONS: dict[str, tuple[str, int]] = {
    "horizontal": ("sgHORIZONTAL2D", 1),
    "sghorizontal2d": ("sgHORIZONTAL2D", 1),
    "vertical": ("sgVERTICAL2D", 1),
    "sgvertical2d": ("sgVERTICAL2D", 1),
    "parallel": ("sgPARALLEL2D", 2),
    "sgparallel2d": ("sgPARALLEL2D", 2),
    "perpendicular": ("sgPERPENDICULAR2D", 2),
    "sgperpendicular2d": ("sgPERPENDICULAR2D", 2),
    "tangent": ("sgTANGENT", 2),
    "sgtangent": ("sgTANGENT", 2),
    "coincident": ("sgCOINCIDENT2D", 2),
    "sgcoincident": ("sgCOINCIDENT2D", 2),
    "equal": ("sgSAMELENGTH", 2),
    "sgequal": ("sgSAMELENGTH", 2),
    "concentric": ("sgCONCENTRIC", 2),
    "sgconcentric": ("sgCONCENTRIC", 2),
    # SK4: colinear / fixed / midpoint (2025 SketchAddConstraints strings confirmed on live COM)
    "colinear": ("sgCOLINEAR", 2),
    "collinear": ("sgCOLINEAR", 2),  # British spelling alias
    "sgcolinear": ("sgCOLINEAR", 2),
    "fixed": ("sgFIXED", 1),
    "sgfixed": ("sgFIXED", 1),
    "midpoint": ("sgATMIDDLE", 2),
    "atmiddle": ("sgATMIDDLE", 2),
    "sgatmiddle": ("sgATMIDDLE", 2),
    # SK5: symmetric (three picks: entity1, entity2, entity3 = symmetry axis)
    "symmetric": ("sgSYMMETRIC", 3),
    "symmetry": ("sgSYMMETRIC", 3),
    "sgsymmetric": ("sgSYMMETRIC", 3),
}

SKETCH_RELATION_HINT = (
    "horizontal / vertical / parallel / perpendicular / tangent / "
    "coincident / equal / concentric / colinear / fixed / midpoint / symmetric"
)

SKETCH_SOLVE_STATES: tuple[str, ...] = ("under_defined", "fully_defined", "over_defined")

AABB_INTERFERENCE_EPS_M = 1e-7
