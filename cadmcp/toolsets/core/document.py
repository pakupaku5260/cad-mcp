"""Core toolset · document lifecycle, configuration, material, BOM query.

Drawing creation/views/BOM live in the drawing toolset (core budget).
"""

from __future__ import annotations

from cadmcp.errors import fail
from cadmcp.kernel import OpContext
from cadmcp.registry import ToolSpec, make_schema
from cadmcp.safety import ensure_input_path, ensure_output_path

from ._common import _DOC_EXTS, _doc_payload


def new_part(ctx: OpContext, template: str | None = None) -> dict:
    return _doc_payload(ctx.backend.new_part(template))


def open_document(ctx: OpContext, path: str) -> dict:
    resolved = ensure_input_path(path, roots=ctx.workspace, extensions=_DOC_EXTS)
    return _doc_payload(ctx.backend.open_document(resolved))


def save_document(ctx: OpContext, path: str, overwrite: bool = False) -> dict:
    resolved = ensure_output_path(path, roots=ctx.workspace, extensions=_DOC_EXTS, overwrite=overwrite)
    ctx.backend.save_as(resolved)
    return {"saved": True, "path": str(resolved)}


def list_configurations(ctx: OpContext) -> dict:
    active, names = ctx.backend.list_configurations()
    return {"active": active, "names": names}


def set_configuration(ctx: OpContext, name: str, create: bool = False) -> dict:
    active, created = ctx.backend.set_configuration(name, create)
    return {"name": active, "created": created}


def get_material(ctx: OpContext) -> dict:
    name, database = ctx.backend.get_material()
    return {"name": name, "database": database}


def set_material(ctx: OpContext, name: str) -> dict:
    applied, database = ctx.backend.set_material(name)
    return {"name": applied, "database": database}


def set_properties(ctx: OpContext, entries: list) -> dict:
    if not isinstance(entries, list) or not entries:
        raise fail(
            "INVALID_ARGUMENT",
            "entries must be a non-empty array",
            '[{"key":"PartNo","value":"P-001"}]',
        )
    cleaned: dict[str, str] = {}
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            raise fail("INVALID_ARGUMENT", f"entries[{i}] must be an object", "Include key/value")
        key = str(item.get("key") or "").strip()
        if not key:
            raise fail("INVALID_ARGUMENT", f"entries[{i}].key cannot be empty", "e.g. PartNo")
        cleaned[key] = str(item.get("value") or "")
    written = ctx.backend.set_properties(cleaned)
    return {"written": written, "count": len(written)}


def get_properties(ctx: OpContext, keys: list | None = None) -> dict:
    want = None
    if keys is not None:
        if not isinstance(keys, list):
            raise fail("INVALID_ARGUMENT", "keys must be an array of strings", '["PartNo","Material"]')
        want = [str(k) for k in keys]
    props = ctx.backend.get_properties(want)
    return {"properties": props, "count": len(props)}


def get_bom(ctx: OpContext) -> dict:
    source, rows = ctx.backend.get_bom()
    return {
        "source": source,
        "count": len(rows),
        "rows": [row.model_dump() for row in rows],
    }


def close_document(ctx: OpContext, discard: bool = False) -> dict:
    info = ctx.backend.active_document()
    if info is None:
        raise fail("NO_ACTIVE_DOCUMENT", "No open document to close",
                   "Call new_part or open_document first")
    if info.modified and not discard:
        raise fail(
            "INVALID_ARGUMENT",
            f"Document {info.title} has unsaved changes; close refused without confirmation",
            "Pass discard=true to discard changes, or save_document first",
            title=info.title,
        )
    ctx.backend.close_document(discard=discard)
    return {"closed": True, "discarded": discard, "title": info.title}


def get_active_document(ctx: OpContext) -> dict:
    info = ctx.backend.active_document()
    if info is None:
        raise fail("NO_ACTIVE_DOCUMENT", "No open document",
                   "Call new_part to create a part, or open_document to open a file")
    return _doc_payload(info)


def list_open_documents(ctx: OpContext) -> dict:
    """Enumerate open documents; mark the active one. Stable sort by title."""
    active = ctx.backend.active_document()
    active_key = None
    if active is not None:
        active_key = (active.title, active.path)
    docs = []
    for info in ctx.backend.list_open_documents():
        item = _doc_payload(info)
        item["active"] = active_key is not None and (info.title, info.path) == active_key
        docs.append(item)
    docs.sort(key=lambda d: (str(d.get("title") or ""), str(d.get("path") or "")))
    # Ensure at most one active after sort (recompute if ties)
    if active_key is not None:
        seen = False
        for item in docs:
            is_active = (item.get("title"), item.get("path")) == active_key and not seen
            item["active"] = is_active
            if is_active:
                seen = True
    return {"count": len(docs), "documents": docs}


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="new_part",
        description="Create a new part and make it active.",
        input_schema=make_schema(
            {"template": {"type": "string", "description": "Optional .prtdot."}}
        ),
        handler=new_part,
        mutating=True,
    ),
    ToolSpec(
        name="open_document",
        description="Open a workspace part/assembly/drawing file.",
        input_schema=make_schema(
            {"path": {"type": "string"}},
            ["path"],
        ),
        handler=open_document,
        mutating=True,
    ),
    ToolSpec(
        name="save_document",
        description="Save the active document into the workspace; overwrite=true to replace.",
        input_schema=make_schema(
            {
                "path": {"type": "string"},
                "overwrite": {"type": "boolean", "description": "Allow overwrite."},
            },
            ["path"],
        ),
        handler=save_document,
        mutating=True,
    ),
    ToolSpec(
        name="close_document",
        description="Close the active document; discard=true drops unsaved changes.",
        input_schema=make_schema(
            {"discard": {"type": "boolean", "description": "Discard unsaved changes."}}
        ),
        handler=close_document,
        mutating=True,
    ),
    ToolSpec(
        name="get_active_document",
        description="Title, path, modified/saved flags, configuration and epoch of the active document.",
        input_schema=make_schema({}),
        handler=get_active_document,
    ),
    ToolSpec(
        name="list_open_documents",
        description="List open documents with DocInfo fields and an active flag for multi-doc context.",
        input_schema=make_schema({}),
        handler=list_open_documents,
        timeout_class="fast",
    ),
    ToolSpec(
        name="list_configurations",
        description="List configurations and the active one.",
        input_schema=make_schema({}),
        handler=list_configurations,
        timeout_class="fast",
    ),
    ToolSpec(
        name="set_configuration",
        description=(
            "Activate a configuration; create=true adds it if missing."
        ),
        input_schema=make_schema(
            {
                "name": {"type": "string"},
                "create": {"type": "boolean", "default": False, "description": "Create if missing."},
            },
            ["name"],
        ),
        handler=set_configuration,
        mutating=True,
    ),
    ToolSpec(
        name="get_material",
        description="Read the material grade and database of the active part.",
        input_schema=make_schema({}),
        handler=get_material,
        timeout_class="fast",
    ),
    ToolSpec(
        name="set_material",
        description=(
            "Assign a material grade to the active part's current configuration."
        ),
        input_schema=make_schema(
            {"name": {"type": "string"}},
            ["name"],
        ),
        handler=set_material,
        mutating=True,
    ),
    ToolSpec(
        name="set_properties",
        description="Write part/assembly custom properties (active config). Extra keys allowed.",
        input_schema=make_schema(
            {
                "entries": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["key", "value"],
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                        },
                    },
                },
            },
            ["entries"],
        ),
        handler=set_properties,
        mutating=True,
    ),
    ToolSpec(
        name="get_properties",
        description="Read part/assembly custom properties; omit keys for the default set.",
        input_schema=make_schema(
            {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Property names; default controlled set when omitted.",
                },
            },
        ),
        handler=get_properties,
        timeout_class="fast",
    ),
    ToolSpec(
        name="get_bom",
        description=(
            "BOM rollup for the active assembly/part, or drawing table rows after insert_bom."
        ),
        input_schema=make_schema({}),
        handler=get_bom,
        timeout_class="fast",
    ),
)
