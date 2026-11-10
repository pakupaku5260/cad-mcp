"""
Resource dual-channel single test (M1 complement, § 8 boundary rule): content source is unique, uri can be parsed, and help is homologous.

Three things to guard:
1. Each topic is registered as` `cadmcp://help/<topic>` `and the body is not empty (empty shell resources are not allowed);
2. The help (topic) tool reads the same text as the resource channel - the same origin, never copying two copies by hand;
3. Unknown topic Go "error is command": invalid_argument + hint lists all available topics.

"""

from __future__ import annotations

import pytest

from cadmcp.errors import CadMcpError
from cadmcp.resources import (
    RESOURCE_SCHEME,
    iter_resources,
    known_topics,
    known_uris,
    read_resource,
    topic_entry,
    topic_uri,
)
from cadmcp.resources.content import MIME_TYPE, TOPICS
from cadmcp.toolsets.core import core_registry


def test_every_topic_registered_readable_nonempty():
    assert tuple(TOPICS) == known_topics()
    for name in known_topics():
        uri = topic_uri(name)
        assert uri in known_uris()
        assert uri == f"{RESOURCE_SCHEME}://help/{name}"
        assert read_resource(uri) == TOPICS[name].text
        assert len(TOPICS[name].text.strip()) > 200, f"{name} body is an empty shell"
        assert TOPICS[name].description.strip()


def test_iter_resources_shape_for_list_channel():
    entries = iter_resources()
    assert len(entries) == len(TOPICS)
    for uri, name, description in entries:
        assert uri == topic_uri(name)
        assert description == TOPICS[name].description


def test_topic_entry_returns_pair_or_none():
    uri, text = topic_entry("workflow")
    assert uri == topic_uri("workflow") and text == TOPICS["workflow"].text
    assert topic_entry("nope") is None


def test_help_tool_reads_same_content_source():
    """§ 8 Boundary rules: The resource channel and the tool channel must be homologous (homologous assertion, anti-drift)."""
    spec = core_registry().get("help")
    assert spec is not None
    assert spec.mutating is False  # read-only tool, always retryable
    payload = spec.handler(None, topic="selectors")  # handler does not need ctx
    assert payload["topic"] == "selectors"
    assert payload["uri"] == topic_uri("selectors")
    assert payload["text"] == read_resource(payload["uri"])
    assert MIME_TYPE == "text/markdown"


def test_help_unknown_topic_is_actionable_error():
    with pytest.raises(CadMcpError) as ei:
        core_registry().get("help").handler(None, topic="nope")
    err = ei.value
    assert err.code == "INVALID_ARGUMENT"
    assert err.context["topic"] == "nope"
    for name in known_topics():  # hint lists all topics — errors are actionable
        assert name in err.hint
