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

from dataclasses import fields, is_dataclass, MISSING, Field, dataclass
from types import UnionType, NoneType
from typing import Any, TypeVar, get_type_hints, Annotated, Optional

from dc_input._types import (
    KeyPath,
    FieldMetadata,
    NotProvided,
    ContainerRegistry,
    GraphStart,
    GraphEnd,
)
from dc_input._utils import (
    get_type_base_args,
    find_schema_in_type_args,
    is_node,
    head,
    safe_issubclass,
    get_optional_non_none,
    link, tail,
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
    mdata_list = _collect_metadata(sc, containers)

    return _get_query_graph(mdata_list)


def _collect_metadata(
    sc: Any,
    containers: ContainerRegistry | None = None,
    _result: list[FieldMetadata] | None = None,
    _path: KeyPath = (),
) -> list[FieldMetadata]:
    """
    Collect metadata for all the fields of the schema.
    """
    containers = containers or {}
    _result = _result or []
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
            parent=sc,
        )

        # Defer nested schemas to preserve intuitive query flow
        if is_node(mdata.type):
            nodes.append(mdata)
            continue
        else:
            _result.append(mdata)

    # Expand nested schemas
    for mdata in nodes:
        _result.append(mdata)

        base, args = get_type_base_args(mdata.type)
        if is_dataclass(base):
            schema_nested = base
        else:
            schema_nested = find_schema_in_type_args(args)

        _collect_metadata(schema_nested, containers, _result, mdata.path)

    return _result


def _get_query_graph(mdata_list: list[FieldMetadata]) -> GraphStart:
    """
    Select relevant fields from the list of field metadata, expand fixed length tuples
    and add skip/repeat edges to fields with supported type patterns.

    Supported patterns (T must be a schema):
    - Optional[T] (skip)
    - list[T], set[T] (skip & repeat)
    - tuple[T, ...] (skip & repeat)

    Returns the head of a linked list of FieldMetadata.
    """
    graph_start = GraphStart()
    mdata_prev = graph_start
    end = GraphEnd()

    i_cur = 0
    while i_cur < len(mdata_list):
        mdata_cur = mdata_list[i_cur]
        print(mdata_cur)
        base, args = get_type_base_args(mdata_cur.type)

        # Fields that do not contain schemas do not need further processing
        if not find_schema_in_type_args(args):
            link(mdata_prev, mdata_cur)
            mdata_prev = mdata_cur
            i_cur += 1
            continue

        # ------------------------------------------------------------------
        # Fixed-length tuple[Schema, Schema, ...]
        # ------------------------------------------------------------------
        if safe_issubclass(base, tuple) and Ellipsis not in args:
            i_tail, tail = _handle_fixed_length_tuple(mdata_list, mdata_cur, args)
            i_cur = i_tail + 1
            mdata_prev = tail
            continue

        # ------------------------------------------------------------------
        # T | None, list[T], set[T], tuple[T, ...]
        # ------------------------------------------------------------------
        if base is UnionType or safe_issubclass(base, (list, set, tuple)):
            # UnionType must be T | None
            assert base is not UnionType or (len(args) == 2 and NoneType in args)
            # Find first node not belonging to this container
            node_path = mdata_cur.path
            remaining = mdata_list[i_cur:]
            skip_from = mdata_list[i_cur + 1]
            try:
                non_child_leaf = lambda x: not _is_child(node_path, x.path) and not is_node(x.type)
                skip_to = next(filter(non_child_leaf, remaining))
            except StopIteration:
                skip_from.skip_to = end
                i_cur += 1
                continue
            else:
                skip_from.skip_to = skip_to
                # Repeatable containers
                base_to_check = get_optional_non_none(mdata_cur.type) if base is UnionType else base
                print(base_to_check)
                if safe_issubclass(base_to_check, (list, set, tuple)):
                    i_last_field_container = mdata_list.index(skip_to) - 1
                    last_field_container = mdata_list[i_last_field_container]
                    last_field_container.repeat_from = skip_from
                    i_cur += 1

        if base is UnionType:
            nested_t = get_optional_non_none(mdata_cur.type)
            nested_base, nested_args = get_type_base_args(nested_t)
            # Edge case: tuple[T, T] | None
            if safe_issubclass(nested_base, tuple) and Ellipsis not in nested_args:
                mdata_cur.type = nested_t
                i_tail, tail = _handle_fixed_length_tuple(
                    mdata_list, mdata_cur, nested_args
                )
                i_cur = i_tail + 1
                mdata_prev = tail
            else:
                i_cur += 1

    link(mdata_prev, end)

    return graph_start


def _handle_fixed_length_tuple(
    mdata_list: list[FieldMetadata], field_cur: FieldMetadata, args: tuple
) -> tuple[int, FieldMetadata]:
    assert len(args) >= 2
    assert all(is_dataclass(arg) for arg in args)
    assert all(arg == args[0] for arg in args)

    i_field_cur = mdata_list.index(field_cur)

    # Collect the subgraph representing ONE tuple element
    start = mdata_list[i_field_cur + 1]
    start.annotation = field_cur.annotation
    start.repeat_n = (1, len(args))
    start.parent = args[0]
    start.skip_to = field_cur.skip_to

    i_after_start_subgraph = i_field_cur + 2
    remaining = mdata_list[i_after_start_subgraph:]
    node_path = field_cur.path
    to_repeat: list[FieldMetadata] = [start]
    for mdata in remaining:
        if not _is_child(node_path, mdata.path):
            break
        mdata.parent = start.parent
        to_repeat.append(mdata)

    result = [*to_repeat]

    # Clone N-1 additional copies
    for n in range(len(args) - 1):
        for fld in to_repeat:
            fld_repeat = FieldMetadata(
                name=fld.name,
                type=fld.type,
                path=fld.path,
                parent=fld.parent,
                annotation=fld.annotation,
                default=fld.default,
                default_factory=fld.default_factory,
            )
            if fld is to_repeat[0]:
                fld_repeat.repeat_n = (n + 2, len(args))

            result.append(fld_repeat)

    # Link up all fields in result
    for prev, cur in zip(result, result[1:]):
        link(prev, cur)

    # Link result to field before current
    before_cur = mdata_list[i_field_cur - 1]
    link(before_cur, start)

    # Index of the tail field within the mdata_list: add one to skip node
    i_tail = i_field_cur + 1 + len(to_repeat)

    return i_tail, tail(start)




def _is_child(parent: KeyPath, child: KeyPath) -> bool:
    return parent == child[: len(parent)]


@dataclass
class B:
    b1: str
    b2: int


@dataclass
class A:
    a1: int
    a2: list[B]
    a3: tuple[list[B], list[B]]



# -------------------------
# Deep leaf schema
# -------------------------
@dataclass
class Address:
    street: str
    number: int
    zip_code: Annotated[str, "ZIP or postal code"]


# -------------------------
# Reusable nested schema
# -------------------------
@dataclass
class Contact:
    email: str
    phone: str | None


# -------------------------
# Schema used in containers
# -------------------------
@dataclass
class Employee:
    name: str
    contact: Contact
    addresses: list[Address]


# -------------------------
# Tuple-heavy schema
# -------------------------
@dataclass
class Department:
    name: str
    # Fixed-size homogeneous tuple
    heads: tuple[Employee, Employee]

    # Repeatable tuple
    assistants: tuple[Employee, ...]


# -------------------------
# Optional + container combo
# -------------------------
@dataclass
class Project:
    title: str
    # Optional nested schema
    lead: Employee | None

    # List of schemas
    contributors: list[Employee]

    # Optional fixed tuple of schemas
    milestones: tuple[Department, Department] | None


# -------------------------
# Root stress-test schema
# -------------------------
@dataclass
class Company:
    name: str

    # Optional container of schemas
    departments: list[Department]

    # Container of schemas with deep nesting
    projects: list[Project]

    # Fixed tuple at root
    founders: tuple[Contact, Contact]

    # Leaf after heavy nesting (ordering stress)
    founded_year: int


res = parse_schema(Company)
print(res)

cur = res
i = 0
while cur:
    print(f"{i:03d}", cur)
    cur = cur.next
    i += 1

# TODO: 008 should not exist

res = parse_schema(A)
cur = res
while True:
    print(cur)
    cur = cur.next


