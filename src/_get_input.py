from __future__ import annotations

from typing import TypeVar

import dc_input._log as log
import dc_input._pipeline as pipeline

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

        Schema rules:

        - The only supported ``Union`` is ``T | None``.
        - ``list``, ``set`` and ``tuple`` may only nest one level
          (a nested schema counts as one level).
        - ``list``, ``set`` and ``tuple`` may not nest ``dict``.
        - ``dict`` values may not be containers or schemas.
        - Fixed-size ``tuple`` with schemas must be homogeneous.

    container_aliases : ContainerAliasRegistry | None, optional
        Mapping that allows registering container-like classes that are not
        subclasses of ``dict``, ``list``, ``set``, or ``tuple``. Subclasses of these
        built-in containers are handled automatically.

        The mapping key is the unparameterized container-like type; the value is
        the container type used internally (e.g. ``list`` or ``list[int]``).

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
    **To place default fields before non-default fields, set** ``kw_only=True``::

        from dataclasses import dataclass

        @dataclass(kw_only=True)
        class Schema:
            val1: str = "default"
            val2: int

    **Register a custom parser for** ``datetime.date``::

        import datetime

        def parse_date_dmy(s: str) -> datetime.time
            s = s.strip().replace(".", "/").replace("-", "/")
            try:
                day, month, year = map(int, s.split("/"))
            except Exception:
                raise ValueError("wrong format, must be DD/MM/YYYY")
            else:
                return datetime.date(year, month, day)

        parsers = {datetime.date: parse_date_dmy}

    **Register container aliases for non-standard container types**::

        class GenericContainerLike[T]:
            def __init__(self, items: list[T]) -> None:
                self._items = items

        class SpecificContainerLike:
            def __init__(self, items: list[int]) -> None:
                self._items = items

        container_aliases = {
            GenericContainerLike: list,
            SpecificContainerLike: list[int],
        }
    """
    log.version()

    container_aliases = container_aliases or {}
    parsers = parsers or {}

    log.schema(schema)
    pipeline.validate_user_definitions(schema, container_aliases, parsers)

    parsers = pipeline.prepare_parsers(parsers)

    normalized_schema = pipeline.normalize_schema(schema, container_aliases)
    log.normalized_schema(normalized_schema)

    session_graph = pipeline.build_session_graph(normalized_schema, schema.__name__)
    log.session_graph(session_graph)

    session_result = pipeline.run_user_session(session_graph, parsers)
    log.session_result(session_result)

    initialized = pipeline.initialize_schema(schema, session_result)
    log.initialized_schema(initialized)

    return initialized
