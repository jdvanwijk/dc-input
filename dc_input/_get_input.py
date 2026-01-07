from __future__ import annotations

from typing import TypeVar

from _pipeline import (
    build_session_graph,
    initialize_schema,
    normalize_schema,
    merge_parsers,
    run_user_session,
    validate_user_definitions,
)
from dc_input._debug import log_normalized_schema, log_session_graph

from dc_input._types import ContainerAliasRegistry, ParserRegistry


T = TypeVar("T")


def get_input(
    schema: type[T],
    *,
    container_aliases: ContainerAliasRegistry | None = None,
    parsers: ParserRegistry | None = None,
) -> T:
    container_aliases = container_aliases or {}
    parsers = parsers or {}

    validate_user_definitions(schema, container_aliases, parsers)
    parsers_merged = merge_parsers(parsers)
    normalized_schema = normalize_schema(schema, container_aliases)
    log_normalized_schema(normalized_schema)
    session_graph = build_session_graph(normalized_schema, schema.__name__)
    log_session_graph(session_graph)
    session_result = run_user_session(session_graph, parsers_merged)

    return initialize_schema(schema, session_result)
