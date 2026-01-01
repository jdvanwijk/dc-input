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

from dataclasses import fields, is_dataclass, Field, dataclass, make_dataclass
from types import UnionType, NoneType
from typing import Any, TypeVar, get_type_hints, Annotated

from dc_input._types import (
    KeyPath,
    Node,
    Leaf,
    ContainerRegistry,
    GraphEnd,
    GraphStart,
    QueryGraphPart,
    NonSchemaRegistry,
)
from dc_input._utils import (
    get_type_base_args,
    find_schema_in_type,
    alt_issubclass,
    get_optional_non_none,
    link,
)

T = TypeVar("T")


def build_query_graph(
    sc: Any, containers: ContainerRegistry, non_schemas: NonSchemaRegistry
) -> GraphStart:
    """
    Parse a schema dataclass into a query graph.

    This is the main public entry point of the module.

    Steps:
    1. Collect metadata for all schema fields.
    2. Expand fixed-size tuples that contain schemas.
    3. Augment with skip and repeat edges.
    4. Link all edges.


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
    # TODO: Completely redo module after normalized schemas

    assert is_dataclass(sc)
    assert isinstance(containers, dict) or containers is None

    first_pass = _collect_metadata(sc, containers, non_schemas)
    second_pass = _expand_nested_tuples(first_pass, non_schemas)
    third_pass = _add_skip_repeat_edges(second_pass, non_schemas)
    fourth_pass = _link_graph(third_pass)

    assert isinstance(fourth_pass, GraphStart)

    return fourth_pass


def _collect_metadata(
    sc: Any, containers: ContainerRegistry, non_schemas: NonSchemaRegistry
) -> list[QueryGraphPart]:
    """
    Collect metadata for all the fields of the schema.
    """

    def _collect(
        sc: Any,
        containers: ContainerRegistry,
        non_schemas: NonSchemaRegistry,
        parent: GraphStart | Node,
        _res: list[Node | Leaf] | None = None,
        _field_name_path: KeyPath = (),
    ) -> list[Node | Leaf]:
        _res = _res or []
        type_hints = get_type_hints(sc, include_extras=True)
        flds = fields(sc)

        nodes: list[tuple[str, Any]] = []
        for fld_name, t in type_hints.items():
            # Defer nested schemas for intuitive query flow
            print(fld_name, t)
            if find_schema_in_type(t, non_schemas):
                nodes.append((fld_name, t))
                continue

            # Extract annotation from t
            t, annotation = _extract_annotation(t)
            # Label optional types, extract union_t from UnionType
            is_optional = False
            base, args = get_type_base_args(t)
            if base is UnionType:
                t = get_optional_non_none(t)
                is_optional = True
            if alt_issubclass(t, (list, set, dict)) or Ellipsis in args:
                is_optional = True

            # Substitute container-likes in registry

            if t_substitue := containers.get(t):
                t = t_substitue

            # Compute field path
            field_path_new = _field_name_path + (fld_name,)

            # Get field defaults
            fld_cur: Field = next(f for f in flds if f.name == fld_name)
            default = fld_cur.default
            def_factory = fld_cur.default_factory

            new_leaf = Leaf(
                name=fld_name,
                type=t,
                field_name_path=field_path_new,
                is_optional=is_optional,
                annotation=annotation,
                default=default,
                default_factory=def_factory,
                parent=parent,
            )
            _res.append(new_leaf)

        # Expand nested schemas
        for fld_name, t in nodes:
            # Extract annotation from t
            t, annotation = _extract_annotation(t)
            if t_substitue := containers.get(t):
                t = t_substitue

            # Get nested schema and name
            base, args = get_type_base_args(t)
            schema_nested = (
                base
                if is_dataclass(base)
                else find_schema_in_type(t, non_schemas)
            )
            name = schema_nested.__name__

            # Compute schema path and field path
            field_path_new = _field_name_path + (fld_name,)

            new_node = Node(
                name=name,
                type=t,
                field_name_path=field_path_new,
                annotation=annotation,
                parent=parent,
            )
            _res.append(new_node)

            _collect(
                schema_nested,
                containers,
                non_schemas,
                new_node,
                _res,
                new_node.field_name_path,
            )

        return _res

    start = GraphStart(name=sc.__name__)
    return [start] + _collect(sc, containers, non_schemas, start) + [GraphEnd()]


def _expand_nested_tuples(graph: list[QueryGraphPart], non_schemas: NonSchemaRegistry) -> list[QueryGraphPart]:
    res: list[QueryGraphPart] = []

    i = 0
    while i < len(graph):
        part_cur = graph[i]

        if not isinstance(part_cur, Node) or not _is_expandable_tuple(part_cur.type, non_schemas):
            res.append(part_cur)
            i += 1
            continue

        # Collect subgraph
        remaining = graph[i + 1 :]
        node_path = part_cur.field_name_path
        subgraph = [
            part
            for part in remaining
            if not isinstance(part, GraphEnd)
            and _is_child(node_path, part.field_name_path)
        ]
        to_repeat = [part_cur] + subgraph

        # Clone subgraph as many times as there are tuple type args
        base, args = get_type_base_args(part_cur.type)
        if base is UnionType:
            non_none = get_optional_non_none(part_cur.type)
            _, args = get_type_base_args(non_none)
        for n in range(len(args)):
            for part in to_repeat:
                assert isinstance(part, (Node, Leaf))

                if isinstance(part, Node):
                    part_clone = Node(
                        name=part.name,
                        type=part.type,
                        field_name_path=part.field_name_path,
                        parent=part.parent,
                        annotation=part.annotation,
                        repeat_n=(n + 1, len(args)) if part is part_cur else (),
                    )
                elif isinstance(part, Leaf):
                    part_clone = Leaf(
                        name=part.name,
                        type=part.type,
                        field_name_path=part.field_name_path,
                        is_optional=part.is_optional,
                        parent=part.parent,
                        annotation=part.annotation,
                        default=part.default,
                        default_factory=part.default_factory,
                    )

                res.append(part_clone)

        i += len(to_repeat)

    return res


def _add_skip_repeat_edges(graph: list[QueryGraphPart], non_schemas: NonSchemaRegistry) -> list[QueryGraphPart]:
    res: list[QueryGraphPart] = []

    for i, part_cur in enumerate(graph):
        part_cur = graph[i]
        if isinstance(part_cur, (GraphStart, GraphEnd)):
            res.append(part_cur)
            continue

        assert isinstance(part_cur, (Node, Leaf))

        # Fields that do not contain schemas do not need further processing
        base, args = get_type_base_args(part_cur.type)
        if not find_schema_in_type(part_cur.type, non_schemas):
            res.append(part_cur)
            continue

        assert isinstance(part_cur, Node)

        # ------------------------------------------------------------------
        # Start of optional fixed-length tuple (tuple[Schema, Schema] | None)
        # ------------------------------------------------------------------
        if (
            base is UnionType
            and _is_expandable_tuple(part_cur.type, non_schemas)
            and part_cur.repeat_n[0] == 1
        ):
            remaining = graph[i + 1 :]
            skip_target = next(
                part
                for part in remaining
                if isinstance(part, GraphEnd)
                or part.field_name_path[: len(part_cur.field_name_path)]
                != part_cur.field_name_path
            )
            assert isinstance(skip_target, (Node, GraphEnd))
            part_cur.skip_target = skip_target
            res.append(part_cur)
            continue

        # ------------------------------------------------------------------
        # T | None, list[T], set[T], tuple[T, ...]
        # ------------------------------------------------------------------
        if base is UnionType or alt_issubclass(base, (list, set, tuple)):
            # Expandable tuple does not need further processing, already expanded
            if _is_expandable_tuple(part_cur.type, non_schemas):
                res.append(part_cur)
                continue

            assert (len(args) == 2 and NoneType in args) or base is not UnionType
            # Find first node not belonging to this container
            remaining = graph[i + 1 :]
            skip_target = next(
                part
                for part in remaining
                if isinstance(part, GraphEnd)
                or not _is_child(part_cur.field_name_path, part.field_name_path)
            )
            assert isinstance(skip_target, (Node, GraphEnd))
            part_cur.skip_target = skip_target

            # Handle repeatable containers
            base_to_check = (
                get_optional_non_none(part_cur.type) if base is UnionType else base
            )
            if alt_issubclass(base_to_check, (list, set, tuple)):
                last_field_container = graph[graph.index(skip_target) - 1]
                assert isinstance(last_field_container, Leaf)
                repeat_entry = graph[i + 1]
                assert isinstance(repeat_entry, Leaf)
                last_field_container.repeat_entry = repeat_entry

        res.append(part_cur)

    return res


def _link_graph(graph: list[QueryGraphPart]) -> GraphStart:
    for prev, cur in zip(graph, graph[1:]):
        link(prev, cur)

    return graph[0]


def _extract_annotation(t: type) -> tuple[type | UnionType, str]:
    def _extract(t_with_annotation: type) -> str:
        base, args = get_type_base_args(t_with_annotation)
        if base is Annotated:
            return args[1]
        for arg in args:
            return _extract(arg)
        return ""

    to_process = make_dataclass("ToProcess", [("type", t)])
    t_without = get_type_hints(to_process)["type"]
    t_with = get_type_hints(to_process, include_extras=True)["type"]
    annotation = _extract(t_with)

    return t_without, annotation


def _is_child(parent: KeyPath, child: KeyPath) -> bool:
    return parent != child and parent == child[: len(parent)]


def _is_expandable_tuple(t: type | UnionType, non_schemas: NonSchemaRegistry) -> bool:
    base, args = get_type_base_args(t)
    if base is UnionType:
        base = get_optional_non_none(t)
    return (
            alt_issubclass(base, tuple)
            and find_schema_in_type(t, non_schemas)
            and Ellipsis not in args
    )


if __name__ == "__main__":
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

    res = build_query_graph(Company)

    cur = res
    i = 0
    while cur:
        print(f"{i:03d} {cur}")
        i += 1
        cur = None if isinstance(cur, GraphEnd) else cur.next
