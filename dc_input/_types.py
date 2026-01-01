from __future__ import annotations

from abc import ABC
from collections.abc import Callable, Container
from dataclasses import dataclass, field, _MISSING_TYPE, fields
from typing import Any, Literal


# ---------- NormalizedField ----------
@dataclass
class NormalizedField:
    type: type
    default: Any | Literal[_MISSING_TYPE.MISSING]
    default_factory: Callable[[], Any] | Literal[_MISSING_TYPE.MISSING]
    annotation: str | None

    shape: FieldShape


@dataclass(frozen=True)
class FieldShape(ABC):
    is_optional: bool


@dataclass(frozen=True)
class LeafShape(FieldShape):
    value_type: type


@dataclass(frozen=True)
class SchemaShape(FieldShape):
    schema_type: type


@dataclass(frozen=True)
class ContainerShape(FieldShape):
    container_type: type
    element: FieldShape


@dataclass(frozen=True)
class FixedTupleShape(FieldShape):
    elements: tuple[LeafShape | FixedTupleShape, ...]


@dataclass(frozen=True)
class FixedSchemaTupleShape(FieldShape):
    schema_type: type
    length: int


@dataclass(frozen=True)
class DictShape(FieldShape):
    key: LeafShape
    value: LeafShape


@dataclass(frozen=True)
class LiteralShape(FieldShape):
    values: tuple[Any, ...]


# ---------- Structs ----------
@dataclass
class Node:
    name: str
    type: type
    field_name_path: KeyPath
    annotation: str = ""
    type_substitute: Any | None = None
    repeat_n: tuple[int, int] = ()
    parent: GraphStart | Node | None = None
    prev: GraphStart | Node | Leaf | None = None
    next: Node | Leaf | None = None
    skip_target: Node | GraphEnd | None = None

    def __repr__(self) -> str:
        return _format_query_part_repr(self)


@dataclass
class Leaf:
    name: str
    type: type
    field_name_path: KeyPath
    annotation: str
    is_optional: bool
    default: Any | Literal[_MISSING_TYPE.MISSING]
    default_factory: Any | Literal[_MISSING_TYPE.MISSING]
    type_substitute: Any | None = None
    parent: GraphStart | Node | None = None
    prev: GraphStart | Node | Leaf | None = None
    next: Node | Leaf | GraphEnd | None = None
    repeat_entry: Leaf | None = None

    def __repr__(self) -> str:
        return _format_query_part_repr(self)


@dataclass
class GraphStart:
    name: str
    next: Node | Leaf | None = None
    type: type = field(init=False)
    field_name_path: KeyPath = field(init=False)

    def __post_init__(self) -> None:
        self.type = GraphStart
        self.field_name_path = ()

    def __repr__(self) -> str:
        return _format_query_part_repr(self)


@dataclass
class GraphEnd:
    prev: Leaf | None = None
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = "GraphEnd"

    def __repr__(self) -> str:
        return _format_query_part_repr(self)


def _format_query_part_repr(part: QueryGraphPart) -> str:
    attrs_fmt = []
    for f in fields(part):
        v = getattr(part, f.name)
        if isinstance(v, (Node, Leaf, GraphStart, GraphEnd)):
            attrs_fmt.append(f"{f.name}={v.__class__.__name__}(name={v.name}, ...)")
        else:
            attrs_fmt.append(f"{f.name}={v}")

    return f"{part.__class__.__name__}({', '.join(attr for attr in attrs_fmt)})"


@dataclass
class UserInput:
    value: Any
    graph_part: Leaf


# ---------- Aliases ----------
ContainerRegistry = dict[type, type]
KeyPath = tuple[str, ...]  # Path to a specific schema field
NonSchemaRegistry = Container[object]
NormalizedSchema = dict[KeyPath, NormalizedField]
ParserFunc = Callable[[str], Any]  # Used to parse a user input value
ParserRegistry = dict[type, ParserFunc]  # Stores value parsers
QueryGraphPart = GraphStart | Node | Leaf | GraphEnd
