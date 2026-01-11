from __future__ import annotations

from typing import TypeVar

from dc_input._debug import log_normalized_schema, log_session_graph, log_schema, log_session_result, \
    log_initialized_schema
from dc_input._pipeline import (
    build_session_graph,
    initialize_schema,
    normalize_schema,
    merge_parsers,
    run_user_session,
    validate_user_definitions,
)
from dc_input._types import ContainerAliasRegistry, ParserRegistry


T = TypeVar("T")


def get_input(
    schema: type[T],
    *,
    container_aliases: ContainerAliasRegistry | None = None,
    parsers: ParserRegistry | None = None,
) -> T:
    """
    Interactively collect user input to construct an instance of a dataclass schema.

    This is the main public entry point of the library. Given a dataclass-based
    schema, it launches an interactive, terminal-driven input session that guides
    the user through all required and optional fields, including nested schemas
    and repeated structures.

    The input flow is fully derived from the schema’s type annotations and metadata:

    - Nested dataclasses introduce contextual grouping.
    - Optional fields may be skipped.
    - Repeated schemas (e.g. ``list[T]``) are handled interactively.
    - Default values and default factories are respected.
    - User input can be undone at any point during the session.

    At the end of the session, the collected inputs are assembled into a fully
    initialized instance of the requested schema type.

    Parameters
    ----------
    schema : type[T]
        The root dataclass type to construct.

    container_aliases : ContainerAliasRegistry | None, optional
        Mapping that allows registering container-like classes that are not
        subclasses of ``dict``, ``list``, ``set``, or ``tuple``. Subclasses of these
        built-in containers are handled automatically.

        The mapping key is the unparameterized container-like type; the value is
        a concrete container type used internally (e.g. ``list``).

    parsers : ParserRegistry | None, optional
        Mapping from types to parsing functions. Parsers are required for types
        that cannot be constructed directly from a string input.

        The mapping key is the unparameterized target type ``T``; the value is a
        callable that takes a string and returns an instance of ``T``.

    Returns
    -------
    T
        An instance of the provided schema type, fully populated with values
        entered by the user.

    Raises
    ------
    ValueError
        If the schema, container aliases, or parsers are invalid.

    Examples
    --------
    >>> from dataclasses import dataclass
    >>> import datetime
    >>> import re
    >>>
    >>> class Foo[T]:   # Custom container-like
    ...     def __init__(self, items: list[T]) -> None:
    ...         self._items = items
    >>>
    >>> def parse_date_dmy(s: str) -> datetime.date:    # Parser
    ...     s_normalized = s.strip().replace(".", "/").replace("-", "/")
    ...     date = "/".split(s_normalized)
    ...     try:
    ...         day = int(date[0])
    ...         month = int(date[1])
    ...         year = int(date[2])
    ...     except Exception:
    ...         raise ValueError("wrong format, must be DD/MM/YYYY")
    ...     else:
    ...         return datetime.date(year, month, day)
    >>>
    >>> @dataclass   # Schema
    ... class Bar:
    ...

    >>> container_aliases = {Foo: list}
    >>> parsers = {datetime.date: parse_date_dmy}
    """
    log_schema(schema)

    container_aliases = container_aliases or {}
    parsers = parsers or {}
    validate_user_definitions(schema, container_aliases, parsers)

    parsers_merged = merge_parsers(parsers)

    normalized_schema = normalize_schema(schema, container_aliases)
    log_normalized_schema(normalized_schema)

    session_graph = build_session_graph(normalized_schema, schema.__name__)
    log_session_graph(session_graph)

    session_result = run_user_session(session_graph, parsers_merged)
    log_session_result(session_result)

    initialized = initialize_schema(schema, session_result)
    log_initialized_schema(initialized)

    return initialized
