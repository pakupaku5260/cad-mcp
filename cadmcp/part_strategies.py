"""Part-type strategy catalog (F21 / #8). Data only — does not run recipes.

Catalog entries point at ``examples/*.json`` recipes. Pure read-only helpers;
no COM / backend / dispatch / executor.
"""
from __future__ import annotations

from typing import Any

# Declarative catalog. ``source_recipe`` paths are repo-relative under examples/.
PART_STRATEGIES: tuple[dict[str, Any], ...] = (
    {
        "id": "plate",
        "part_type": "plate",
        "description": "Thin rectangular plate: sketch rectangle then blind extrude.",
        "source_recipe": "examples/skill_case_1_plate.json",
        "required_toolsets": ("core",),
        "feature_tools": (
            "new_part",
            "start_sketch",
            "sketch_rectangle",
            "end_sketch",
            "extrude",
            "get_mass_properties",
        ),
        "key_params": {"width": 80, "height": 50, "thickness": 5, "unit": "mm"},
    },
    {
        "id": "box",
        "part_type": "box",
        "description": "Solid cube/box: square sketch extruded to equal depth.",
        "source_recipe": "examples/box_recipe.json",
        "required_toolsets": ("core",),
        "feature_tools": (
            "new_part",
            "start_sketch",
            "sketch_rectangle",
            "end_sketch",
            "extrude",
            "get_mass_properties",
        ),
        "key_params": {"side": 50, "depth": 50, "unit": "mm"},
    },
    {
        "id": "fillet_pattern",
        "part_type": "fillet_pattern",
        "description": "Extruded profile with fillet then linear pattern of the boss.",
        "source_recipe": "examples/skill_case_2_fillet_pattern.json",
        "required_toolsets": ("core", "sketch_adv"),
        "feature_tools": (
            "new_part",
            "start_sketch",
            "sketch_line",
            "add_sketch_relation",
            "end_sketch",
            "extrude",
            "fillet",
            "linear_pattern",
            "get_geometry",
        ),
        "key_params": {
            "depth": 10,
            "fillet_radius": 2,
            "pattern_count": 3,
            "pattern_dx": 50,
            "unit": "mm",
        },
    },
    {
        "id": "surface_thicken",
        "part_type": "surface_thicken",
        "description": "Surface extrude then thicken (requires features_adv toolbox).",
        "source_recipe": "examples/skill_case_3_surface_thicken.json",
        "required_toolsets": ("core", "features_adv"),
        "feature_tools": (
            "list_toolboxes",
            "open_toolbox",
            "new_part",
            "start_sketch",
            "sketch_rectangle",
            "end_sketch",
            "extrude_surface",
            "thicken",
            "get_mass_properties",
        ),
        "key_params": {"surface_depth": 15, "thickness": 2, "unit": "mm"},
    },
)

_BY_ID: dict[str, dict[str, Any]] = {s["id"]: s for s in PART_STRATEGIES}


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Copy a catalog row with list/tuple fields JSON-friendly."""
    return {
        "id": row["id"],
        "part_type": row["part_type"],
        "description": row["description"],
        "source_recipe": row["source_recipe"],
        "required_toolsets": list(row["required_toolsets"]),
        "feature_tools": list(row["feature_tools"]),
        "key_params": dict(row["key_params"]),
    }


def list_part_strategies(part_type: str | None = None) -> list[dict[str, Any]]:
    """Return catalog rows; ``None`` = all; unknown ``part_type`` → empty list."""
    if part_type is None:
        return [_public_row(s) for s in PART_STRATEGIES]
    wanted = str(part_type).strip()
    if not wanted:
        return []
    return [_public_row(s) for s in PART_STRATEGIES if s["part_type"] == wanted]


def get_part_strategy(strategy_id: str) -> dict[str, Any] | None:
    """Return one catalog row by id, or None if unknown (internal/test helper)."""
    row = _BY_ID.get(str(strategy_id).strip())
    return None if row is None else _public_row(row)


__all__ = [
    "PART_STRATEGIES",
    "get_part_strategy",
    "list_part_strategies",
]
