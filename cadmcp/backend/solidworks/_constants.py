""" COM Backend · Constants & Enumeration.

Source: com_backend.py module-level constants.Check line by line when moving in, no omissions.
"""
from __future__ import annotations

SW_MAIN_WINDOW_CLASS = "SWFrame"
SW_MAIN_WINDOW_TITLE = "SOLIDWORKS"

SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2
SW_DOC_DRAWING = 3
SW_DOC_TYPE_NAMES = {SW_DOC_PART: "part", SW_DOC_ASSEMBLY: "assembly", SW_DOC_DRAWING: "drawing"}
SW_PREF_TEMPLATE_FOLDER = 6

# list_features Skipped Tree Nodes
_SKIP_FEATURE_TYPES = {
    "ProfileFeature", "3DProfileFeature", "RefPlane", "OriginProfileFeature", "DetailCabinet",
}
_SKETCH_FEATURE_TYPES = frozenset({"ProfileFeature", "3DProfileFeature"})

# IFeatureManager.InsertRefPlane constraints
_SW_REFPLANE_DISTANCE = 8
_SW_REFPLANE_ANGLE = 2
_SW_REFPLANE_COINCIDENT = 4

# InsertMirrorFeature mark
_SW_MIRROR_FEAT_MARK = 1
_SW_MIRROR_PLANE_MARK = 2
_SW_MIRROR_BODY_MARK = 256

# FeatureExtruRefSurface3 tail parameters (2025 detection: 22 parameters)
_SURFACE_EXTRU_TAIL = (
    False, False, False, False, 0.0, 0.0,
    False, False, False, False, True, True, True, False, False,
)

# InsertProtrusionBlend 17 (2025 detection: Blend 17 can be built and laid out)
_LOFT_BOSS_ARGS = (
    False, True, False, False, False, False, False, False,
    0.0, 0.0,
    0, 0, 0, 0, 0, 0, 0,
)
# InsertCutBlend 12 gauge (2025 probe: buildable resectable lofting)
_LOFT_CUT_ARGS = (
    False, True, False, False, False, False, False, False,
    0.0, 0.0,
    0, 0,
)
# Center line lofting: mark of line Segment Select4. Entire sketch mark = 4 without features (2025 detection).
_LOFT_CENTERLINE_MARK = 4

# face types (swSurfaceTypes_e)
_SURFACE_KINDS = {
    4001: "plane",
    4002: "cylinder",
    4003: "cone",
    4004: "sphere",
    4005: "torus",
    4006: "bspline",
    4007: "blend",
    4008: "offset",
    4009: "extrusion",
    4010: "revolution",
}
# Edge types (swCurveTypes_e subset)
_CURVE_KINDS = {3001: "line", 3002: "circle", 3003: "ellipse"}

# swSelectType_e
_SEL_EDGE = 1
_SEL_FACE = 2

# swMateType_e
_MATE_COINCIDENT = 0
_MATE_CONCENTRIC = 1
_MATE_TANGENT = 4
_MATE_DISTANCE = 5
_MATE_ANGLE = 6
_MATE_SCREW = 17
_MATE_ERR_NONE = 1  # swAddMateError_NoError

# swComponentSuppressionState_e
_SW_COMP_SUPPRESSED = 0
_SW_COMP_LIGHTWEIGHT = 1
_SW_COMP_RESOLVED = 2

# swMateAlign_e
_MATE_ALIGN_ALIGNED = 0
_MATE_ALIGN_ANTI = 1
_MATE_ALIGN_CLOSEST = 2

_MATE_ERR_HINTS = {
    2: "Fit type does not match the selected entity (e.g. cylinder/axis to be selected for concentric fit)",
    3: "Alignment cannot be satisfied - change one entity or use distance/angle fit instead",
    4: "The selected entity is not suitable for this fit type",
    5: "Fitting will over-define the assembly - delete or modify existing fitting first",
    6: "Invalid gear ratio parameter",
}

# swRebuildOnActivation_e
_DONT_REBUILD_ON_ACTIVATION = 1

# SolidWorks Feature Type Name → Protocol kind
_FEATURE_KINDS = {
    "Extrusion": "extrude", "Cut": "extrude_cut", "ICE": "extrude_cut",
    "Revolution": "revolve",
    "RevCut": "revolve_cut", "Fillet": "fillet", "Chamfer": "chamfer",
    "Shell": "shell", "LPattern": "pattern", "CirPattern": "circular_pattern",
    "MirrorPattern": "mirror", "MirrorSolid": "mirror",
    "Helix": "helix",
    "Sweep": "sweep", "Swept": "sweep",
    "CutSweep": "sweep_cut", "SweepCut": "sweep_cut", "SweptCut": "sweep_cut",
    "Blend": "loft", "Loft": "loft",
    "BlendCut": "loft_cut", "CutBlend": "loft_cut", "LoftCut": "loft_cut",
    "ExtruRefSurface": "extrude_surface",
    "SewRefSurface": "knit",
    "FillRefSurface": "fill_surface",
    "BlendRefSurface": "boundary_surface",
    "NetBlend": "boundary_surface",
    "TrimRefSurface": "trim_surface",
    "ExtendRefSurface": "extend_surface",
    "UnTrimRefSurf": "untrim_surface",
    "Thicken": "thicken",
    "Rib": "rib",
    "Draft": "draft",
    "CombineBodies": "combine",
    "MoldPartingLine": "parting_line",
    "MoldPartingGeom": "parting_surface",
    "MoldShutOffSrf": "shut_off_surface",
    "BaseBody": "stock",
    "DeleteBody": "delete_body",
    "LocalCirPattern": "local_cir_pattern",
    "LocalLPattern": "local_l_pattern",
    "SMBaseFlange": "base_flange",
    "EdgeFlange": "edge_flange",
    "SheetMetal": "sheet_metal",
    "FlatPattern": "flat_pattern",
    "HoleWzd": "hole_wizard",
}

_HELIX_FEATURE_TYPES = {"Helix", "RefCurve", "ReferenceCurve"}
# swHelixDefinedBy_e
_HELIX_PITCH_REV = 0
_HELIX_HEIGHT_PITCH = 2

# RPC disconnect HRESULT
_SERVER_GONE_HRESULTS = {
    -2147417848,  # RPC_E_DISCONNECTED
    -2147023174,  # RPC_S_SERVER_UNAVAILABLE
    -2147023170,  # RPC_S_CALL_FAILED
    -2147418105,  # RPC_E_SERVER_DIED
    -2147023179,  # RPC_S_UNKNOWN_IF
}

# swDeleteSelectionOptions_e
_DELETE_CHILDREN = 1
_DELETE_ABSORBED = 2

# swFeatureSuppressionAction_e / swInConfigurationOpts_e
_SUPPRESS_FEATURE = 0
_UNSUPPRESS_FEATURE = 1
_THIS_CONFIGURATION = 1

# swUserPreferenceToggle_e
_SW_INPUT_DIM_VAL_ON_CREATE = 10
_SW_SETVALUE_CURRENT_CFG = 0

# swUserPreferenceIntegerValue_e (EXP3 True Detection Lock)
_SW_STL_QUALITY = 78  # swSTLQuality
_SW_STEP_AP = 75  # swStepAP
# swSTLQuality_e
_SW_STL_COARSE = 1
_SW_STL_FINE = 2
# DXF/DWG Export (swconst.tlb 2025)
_SW_DXF_MAPPING = 8  # swDxfMapping — Custom map pop-up, product off by default
_SW_DXF_DONT_SHOW_MAP = 21  # swDXFDontShowMap — Force True on Export
# swDxfUseSolidworksLayers = 305 On/Off Timestamp only, no encapsulation

# Screenshot Hide Configuration
_SW_DISPLAY_CURVES = 195
_SW_DISPLAY_SKETCHES = 196
_SW_VIEW_HIDE_ALL_TYPES = 198
_SW_PREF_NO_OPTION = 0

# swStandardViews_e
_VIEW_IDS = {
    "front": 1, "back": 2, "left": 3, "right": 4, "top": 5,
    "bottom": 6, "isometric": 7, "trimetric": 8, "dimetric": 9,
}

# swDimensionType_e
_DIM_KIND = {0: "length", 1: "angle", 2: "length", 3: "length"}
