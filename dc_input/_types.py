from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass, field, fields, _MISSING_TYPE, MISSING, is_dataclass
from typing import Any, Generic, Literal, TypeVar


# ---------- UserInput ----------
@dataclass(frozen=True)
class UserInput:
    """
    Captures a concrete value entered by the user during a session.

    Associates the raw value with the InputStep that produced it,
    enabling reconstruction.
    """

    value: Any
    input_step: InputStep


# ---------- SessionStep ----------
@dataclass
class SessionStep(ABC):
    """
    Base class for all nodes in the interactive session graph.

    SessionSteps form a directed graph representing the order, nesting,
    repetition, and navigation (undo/skip) of user interaction.
    """

    pass


@dataclass
class SessionStart(SessionStep):
    """
    Entry point of an interactive input session.
    """

    name: str
    next: ContextEntry | InputStep | None = None
    parent: None = None

    def __repr__(self) -> str:
        return _format_repr(self)


@dataclass
class ContextEntry(SessionStep):
    """
    Session step representing entry into a nested schema or schema-container context.

    ContextEntries do not collect values themselves; they group and control
    traversal of child InputSteps, ContextEntries and ContextExits.
    """

    field: NormalizedField[ExpandableShape]
    position_info: PositionInfo | None = None

    parent: SessionStart | ContextEntry | None = None
    skip_target: ContextEntry | InputStep | SessionEnd | RepeatExit | None = None
    prev: SessionStart | ContextEntry | InputStep | RepeatExit | None = None
    next: ContextEntry | InputStep | None = None

    @property
    def name(self) -> str:
        return self.field.path[-1]

    def __post_init__(self) -> None:
        assert isinstance(self.field.shape, ExpandableShape)

    def __repr__(self) -> str:
        return _format_repr(self)


@dataclass(frozen=True)
class PositionInfo:
    """
    Additional context information for when the context's field shape is a FixedSchemaContainer.
    """

    n_repeat: int
    total_repeats: int


@dataclass
class InputStep(SessionStep):
    """
    Session step representing a single unit of user input.

    InputSteps correspond one-to-one with TerminalShapes and produce a concrete
    value that contributes to the final result.
    """

    field: NormalizedField[TerminalShape]
    parent: SessionStart | ContextEntry | None = None
    prev: SessionStart | ContextEntry | InputStep | None = None
    next: ContextEntry | InputStep | SessionEnd | None = None

    def __post_init__(self) -> None:
        assert isinstance(self.field.shape, TerminalShape)

    @property
    def name(self) -> str:
        return self.field.path[-1]

    def __repr__(self) -> str:
        return _format_repr(self)


@dataclass
class RepeatExit(SessionStep):
    context: ContextEntry
    element_start: ContextEntry | InputStep
    prev: SessionStep | None = None
    next: SessionStep | None = None
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"RepeatExit for '{self.context.name}'"

    def __repr__(self) -> str:
        return _format_repr(self)


@dataclass
class SessionEnd(SessionStep):
    """
    Terminal step of an interactive input session.
    """

    prev: InputStep | None = None
    next: None = field(init=False)
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = "SessionEnd"
        self.next = None

    def __repr__(self) -> str:
        return _format_repr(self)


def _format_repr(obj: Any) -> str:
    assert is_dataclass(obj)

    attrs_fmt = []
    for f in fields(obj):
        v = getattr(obj, f.name)
        if v is MISSING:
            v = "MISSING"

        if isinstance(v, SessionStep):
            attrs_fmt.append(f"{f.name}={v.__class__.__name__}(name={v.name}, ...)")
        else:
            attrs_fmt.append(f"{f.name}={v}")

    return f"{obj.__class__.__name__}({', '.join(attr for attr in attrs_fmt)})"


# ---------- NormalizedField ----------
T = TypeVar("T", "ExpandableShape", "TerminalShape")


@dataclass(frozen=True)
class NormalizedField(Generic[T]):
    """
    NormalizedField represents a single field derived from a schema,
    enriched with all metadata required for interactive input collection.

    It's the bridge between schema-analysis and runtime session execution.

    Attributes
    ----------
    path:
        Fully-qualified key path to this field within the root schema.
        Used for naming and result assembly.

    type:
        The original Python type annotation of the field, stripped of Annotation and UnionType.

    is_optional:
        True when the original type annotation was UnionType[T, None].

    default:
        Default value if the field is skipped, or MISSING if none exists.

    default_factory:
        Callable producing a default value, or MISSING if none exists.

    annotation:
        Optional human-readable annotation (e.g. format hints, descriptions)
        used for UX presentation.

    shape:
        Structural shape describing how this field is traversed and/or prompted.
        This determines whether the field expands into nested schema traversal
        or is collected as a terminal value.
    """

    path: KeyPath
    type: type
    is_optional: bool
    default: Any | Literal[_MISSING_TYPE.MISSING]
    default_factory: Callable[[], Any] | Literal[_MISSING_TYPE.MISSING]
    annotation: str | None

    shape: T

    def __repr__(self) -> str:
        return _format_repr(self)


# ---------- ExpandableShape, TerminalShape ----------
@dataclass(frozen=True)
class ExpandableShape(ABC):
    """
    Marker base class for shapes that expand into nested schema traversal.

    ExpandableShapes do not directly collect user input. Instead, they introduce
    one or more ContextSteps into the session graph.
    """

    pass


@dataclass(frozen=True)
class TerminalShape(ABC):
    """
    Marker base class for shapes that are collected as terminal user input.

    TerminalShapes always correspond to exactly one InputStep in the session graph,
    even if their resulting Python value is structurally complex (e.g. containers).
    """

    pass


@dataclass(frozen=True)
class FixedSchemaContainerShape(ExpandableShape):
    """
    Shape representing a homogenuous, fixed-size container of schemas.

    Each position corresponds to a schema instance, and the container length
    is known in advance.
    """

    container_type: type
    schema_type: type
    length: int


@dataclass(frozen=True)
class SchemaShape(ExpandableShape):
    """
    Shape representing a dataclass schema.

    Expands into one ContextStep whose children correspond to the schema's fields.
    """

    schema_type: type


@dataclass(frozen=True)
class SchemaContainerShape(ExpandableShape):
    """
    Shape representing a homogenuous container of dataclass schemas (e.g. list[T]).

    Each element expands into its own nested schema traversal. The container length is not known in advance.
    """

    container_type: type
    schema_type: type


@dataclass(frozen=True)
class AtomicShape(TerminalShape):
    """
    AtomicShape represents values that are entered as a single unit and do not expand into nested
    schema traversal, regardless of their underlying Python type.
    """

    value_type: type


@dataclass(frozen=True)
class ContainerShape(TerminalShape):
    """
    Shape representing a homogeneous container of terminal elements.

    Although the resulting value is a container, it is collected as a single
    logical input sequence rather than expanding schema traversal.
    """

    container_type: type
    element: AtomicShape | ContainerShape | FixedContainerShape | LiteralShape


@dataclass(frozen=True)
class DictShape(TerminalShape):
    """
    Shape representing a dictionary entered as terminal input.

    Both keys and values must be atomic.
    """

    key: AtomicShape
    value: AtomicShape


@dataclass(frozen=True)
class FixedContainerShape(TerminalShape):
    """
    Shape representing a fixed-size container of terminal elements.

    Each element may have a different shape, but none expand into schema traversal.
    """

    container_type: type
    elements: tuple[
        AtomicShape | ContainerShape | FixedContainerShape | LiteralShape, ...
    ]


@dataclass(frozen=True)
class LiteralShape(TerminalShape):
    """
    Shape representing a Literal[...] value.

    User input must match one of the allowed literal values.
    """

    values: tuple[Any, ...]


# ---------- Aliases ----------
ContainerAliasRegistry = dict[type, type]
KeyPath = tuple[str, ...]  # Path to a specific schema field
NormalizedSchema = dict[KeyPath, NormalizedField]
ParserFunc = Callable[[str], Any]  # Used to parse a user input value
ParserRegistry = dict[type, ParserFunc]  # Stores value parsers
SessionResult = list[UserInput]
