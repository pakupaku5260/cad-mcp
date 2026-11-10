"""URI registry and static help content for the dual resource channel (v4 §9/§8).

- RESOURCE_SCHEME: project resource URI scheme; every ``cadmcp://…`` that appears in
  tool descriptions must be registered via known_uris() — contract tests enforce
  that instructional resource links are never dead.
- Dual-channel same source (§8): each content.TOPICS entry is registered at import
  as ``cadmcp://help/<topic>``; MCP resources/read and the core help tool both read
  the same body — clients without a resource bridge fall back to the tool, and
  vice versa.
- Wave-7 skills: ``cadmcp://skill/<id>`` shares source with
  ``cadmcp/resources/content/skills/*.md``.
"""
from __future__ import annotations

from collections.abc import Callable

from cadmcp.resources.content import TOPICS
from cadmcp.skills import SKILL_IDS, load_skill_text, skill_uri

RESOURCE_SCHEME = "cadmcp"

_RESOURCES: dict[str, Callable[[], str]] = {}


def register_resource(uri: str, loader: Callable[[], str]) -> None:
    if not uri.startswith(f"{RESOURCE_SCHEME}://"):
        raise ValueError(f"Resource URI must start with {RESOURCE_SCHEME}://: {uri}")
    if uri in _RESOURCES:
        raise ValueError(f"Duplicate resource registration: {uri}")
    _RESOURCES[uri] = loader


def topic_uri(name: str) -> str:
    """Topic resource URI: scheme + help + name, no version (§8 companion rule)."""
    return f"{RESOURCE_SCHEME}://help/{name}"


for _topic_name in TOPICS:  # register on import; default-arg binds current topic (avoids B023)
    register_resource(topic_uri(_topic_name), lambda _n=_topic_name: TOPICS[_n].text)

for _skill_id in SKILL_IDS:
    register_resource(skill_uri(_skill_id), lambda _n=_skill_id: load_skill_text(_n))


def known_uris() -> frozenset[str]:
    return frozenset(_RESOURCES)


def read_resource(uri: str) -> str:
    loader = _RESOURCES.get(uri)
    if loader is None:
        raise KeyError(uri)
    return loader()


def known_topics() -> tuple[str, ...]:
    return tuple(TOPICS)


def topic_entry(name: str) -> tuple[str, str] | None:
    """(uri, body); unknown topic returns None — caller supplies the error text."""
    if name not in TOPICS:
        return None
    return topic_uri(name), TOPICS[name].text


def iter_resources() -> list[tuple[str, str, str]]:
    """For resources/list: (uri, name, description) in TOPICS declaration order."""
    return [(topic_uri(name), name, TOPICS[name].description) for name in TOPICS]
