"""
Schema parsing and query-graph construction.

DEV NOTES
---------
This module is responsible for converting a dataclass-based schema into a
linear, navigable query graph that can later be consumed by an interactive
input engine.

Key ideas:

1. Query graph, not a tree
   -----------------------
   Although schemas are structurally trees, we flatten them into a linked list
   (with optional jump/repeat edges) to enable easy undo, skipping and repetition handling.

2. Nodes vs leaves
   ----------------
   - "Leaf" fields correspond to actual user input prompts.
   - "Node" fields represent structural elements (nested schemas, containers with nested schemas)
     and may introduce control flow (skip / repeat).

3. Two-phase graph construction
   ------------------------------
   - Phase 1: `_get_base_query_graph`
       Builds a linear graph of fields, expanding nested schemas.
   - Phase 2: `_add_repeats_skips_to_graph`
       Adds control-flow edges for Optional, containers, and tuples.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, MISSING, Field
from types import UnionType, NoneType
from typing import Any, TypeVar, get_type_hints, Annotated

from dc_input._types import (
    KeyPath,
    FieldMetadata,
    NotProvided,
    ContainerRegistry,
    GraphEnd,
    GraphStart,
)
from dc_input._utils import (
    get_type_base_args,
    find_schema_in_type_args,
    is_node,
    head,
    safe_issubclass,
    tail, get_optional_non_none,
)

T = TypeVar("T")


def parse_schema(sc: Any, containers: ContainerRegistry | None = None) -> FieldMetadata:
    """
    Parse a schema dataclass into a query graph.

    This is the main public entry point of the module.

    Steps:
    1. Build a base query graph (linear linked list).
    2. Augment the graph with skip and repeat edges.

    Parameters
    ----------
    sc:
        The schema dataclass to parse.
    containers:
        Optional registry mapping "container-like" types to their effective
        schema representation (e.g. CustomList -> list[T]).

    Returns
    -------
    FieldMetadata
        The head of the query graph.
    """
    query_graph = _get_base_query_graph(sc, containers)
    _add_repeats_skips_to_graph(head(query_graph))

    return head(query_graph)


def _get_base_query_graph(
    sc: Any, containers: ContainerRegistry | None = None
) -> GraphStart:
    """
    Build the base query graph for a schema.

    This phase:
    - Expands nested schemas
    - Produces a linear linked list of FieldMetadata
    - Defers container semantics (repeat / skip) to a later phase
    """

    def _extend_graph(
        sc: Any,
        prev: FieldMetadata,
        containers: ContainerRegistry | None = None,
        _path: KeyPath = (),
    ) -> None:
        containers = containers or {}
        type_hints = get_type_hints(sc, include_extras=True)
        flds = fields(sc)

        nodes: list[FieldMetadata] = []

        for fld_name, t in type_hints.items():
            base, args = get_type_base_args(t)

            # Handle container-like type substitution
            t_to_match = t
            if base in (Annotated, UnionType):
                t_to_match = args[0]

            if container_like := containers.get(t_to_match):
                if base is Annotated:
                    t = Annotated[container_like, args[1]]
                elif base is UnionType:
                    t = container_like | None
                else:
                    t = container_like

            # Compute field path
            fld_path = _path + (fld_name,)

            # Handle Annotated[T, "description"]
            annotation = ""
            if base is Annotated:
                t = args[0]
                annotation = args[1]

            # Extract defaults
            fld_cur: Field = next(filter(lambda x: x.name == fld_name, flds))
            default = fld_cur.default if fld_cur.default is not MISSING else NotProvided
            default_factory = (
                fld_cur.default_factory
                if fld_cur.default_factory is not MISSING
                else NotProvided
            )

            mdata = FieldMetadata(
                name=fld_name,
                type=t,
                path=fld_path,
                annotation=annotation,
                default=default,
                default_factory=default_factory,
            )

            # Defer nested schemas to preserve intuitive query flow
            if is_node(mdata.type):
                nodes.append(mdata)
                continue

            if prev:
                mdata.prev = prev
                prev.next = mdata

            prev = mdata

        # Expand nested schemas
        for mdata in nodes:
            base, args = get_type_base_args(mdata.type)
            if is_dataclass(base):
                schema_nested = base
            else:
                schema_nested = find_schema_in_type_args(args)

            if prev:
                mdata.prev = prev
                prev.next = mdata

            _extend_graph(schema_nested, mdata, containers, mdata.path)

    graph = GraphStart(name=sc.__name__)
    _extend_graph(sc, graph, containers)
    last = GraphEnd(prev=tail(graph))
    tail(graph).next = last

    return graph


def _add_repeats_skips_to_graph(graph: FieldMetadata) -> None:
    """
    Augment a base query graph with skip and repeat edges.

    This pass interprets container semantics *after* the base graph has been
    constructed. The graph is modified in-place.

    Supported patterns (T must be a schema):
    - Optional[T]
    - list[T], set[T]
    - tuple[T, ...]
    - fixed-length tuple[T, T, ...]
    """
    field_cur = head(graph)

    while field_cur and field_cur.next:
        base, args = get_type_base_args(field_cur.type)
        field_next = field_cur.next
        # Skip fields that do not contain schemas
        if not find_schema_in_type_args(args):
            field_cur = field_next
            continue

        # ------------------------------------------------------------------
        # Fixed-length tuple[Schema, Schema, ...]
        # ------------------------------------------------------------------
        if safe_issubclass(base, tuple) and Ellipsis not in args:
            field_cur = _handle_fixed_length_tuple(field_cur, args)
            continue

        # ------------------------------------------------------------------
        # Optional[T], list[T], set[T], tuple[T, ...]
        # ------------------------------------------------------------------
        if base is UnionType or safe_issubclass(base, (list, set, tuple)):
            # UnionType must be Optional[T]
            assert base is not UnionType or (len(args) == 2 and NoneType in args)
            # Find first node not belonging to this container
            node_path = field_cur.path
            skip_to = field_cur
            while skip_to.next:
                skip_to = skip_to.next
                if skip_to.path[: len(node_path)] != node_path:
                    break

            field_cur.skip_to = skip_to
            # Repeatable containers
            if base is not UnionType:
                skip_to.prev.repeat_from = field_cur

        # Edge case: tuple[T, T] | None
        field_next = field_cur.next
        if base is UnionType:
            nested_t = get_optional_non_none(field_cur.type)
            nested_base, nested_args = get_type_base_args(nested_t)
            if safe_issubclass(nested_base, tuple) and Ellipsis not in nested_args:
                field_cur.type = nested_t
                field_next = _handle_fixed_length_tuple(field_cur, nested_args)

        field_cur = field_next


def _handle_fixed_length_tuple(field_cur: FieldMetadata, args: tuple) -> FieldMetadata:
    assert len(args) >= 2
    assert all(is_dataclass(arg) for arg in args)
    assert all(arg == args[0] for arg in args)

    node_path = field_cur.path

    # Collect the subgraph representing ONE tuple element
    to_repeat: list[FieldMetadata] = []
    n_repeats = len(args)
    first_field = FieldMetadata(
        name=field_cur.name,
        type=args[0],
        path=field_cur.path,
        annotation=field_cur.annotation,
        repeat_n=(1, n_repeats),
        prev=field_cur.prev,
        next=field_cur.next,
        skip_to=field_cur.skip_to,
    )

    first_field.prev.next = first_field
    first_field.next.prev = first_field
    to_repeat.append(first_field)

    field_to_check = field_cur.next
    while field_to_check and field_to_check.path[: len(node_path)] == node_path:
        to_repeat.append(field_to_check)
        field_to_check = field_to_check.next

    end_of_original = field_to_check  # first node *after* tuple contents

    link_with = to_repeat[-1]

    # Clone N-1 additional copies
    for n in range(n_repeats - 1):
        for fld in to_repeat:
            fld_repeat = FieldMetadata(
                name=fld.name,
                type=fld.type,
                path=fld.path,
                annotation=fld.annotation,
                default=fld.default,
                default_factory=fld.default_factory,
            )
            if fld is to_repeat[0]:
                fld_repeat.repeat_n = (n + 2, n_repeats)

            link_with.next = fld_repeat
            fld_repeat.prev = link_with
            link_with = fld_repeat

    # Reconnect graph tail
    link_with.next = end_of_original
    if end_of_original:
        end_of_original.prev = link_with

    # Jump cursor past the expanded region
    return end_of_original
