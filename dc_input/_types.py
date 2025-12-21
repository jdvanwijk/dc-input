from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


# ---------- Sentinels ----------
class NotProvided:
    """A missing value that can have None as a valid non-missing value"""

    pass


# ---------- Structs ----------
@dataclass
class FieldMetadata:
    """Metadata of a schema field"""

    name: str
    type: type
    path: KeyPath
    annotation: str = ""
    repeat_n: tuple[int, int] = ()
    default: Any | NotProvided = NotProvided
    default_factory: Any | NotProvided = NotProvided
    parent: Any = None
    prev: FieldMetadata | None = None
    next: FieldMetadata | None = None
    repeat_from: FieldMetadata | None = None
    skip_to: FieldMetadata | None = None

    def __str__(self):
        prev = self.prev and f"FieldMetadata(name={self.prev.name}, ...)"
        next = self.next and f"FieldMetadata(name={self.next.name}, ...)"
        repeat_from = (
            self.repeat_from and f"FieldMetadata(name={self.repeat_from.name}, ...)"
        )
        skip_to = self.skip_to and f"FieldMetadata(name={self.skip_to.name}, ...)"

        return (
            f"FieldMetaData("
            f"name={self.name}, "
            f"type={self.type}, "
            f"path={self.path}, "
            f"parent={self.parent}, "
            f"annotation={self.annotation}, "
            f"repeat_n={self.repeat_n}, "
            f"default={self.default}, "
            f"default_factory={self.default_factory}, "
            f"prev={prev}, "
            f"next={next}, "
            f"repeat_from={repeat_from}, "
            f"skip_to={skip_to})"
        )


@dataclass
class GraphStart(FieldMetadata):
    next: FieldMetadata | None = None
    name: str = field(init=False)
    path: KeyPath = field(init=False)
    type: type = field(init=False)

    def __post_init__(self) -> None:
        self.name = "GraphStart"
        self.path = ()
        self.type = GraphStart


@dataclass
class GraphEnd(FieldMetadata):
    prev: FieldMetadata | None = None
    name: str = field(init=False)
    path: KeyPath = field(init=False)
    type: type = field(init=False)

    def __post_init__(self) -> None:
        self.name = "GraphEnd"
        self.path = ()
        self.type = GraphEnd


@dataclass
class UserInput:
    field: FieldMetadata
    value: Any | NotProvided = NotProvided
    prev: UserInput | None = None
    next: UserInput | None = None


# ---------- Aliases ----------
ContainerRegistry = dict[type, type]
InputResult = list[UserInput]
KeyPath = tuple[str, ...]  # Path to a specific schema field
ParserFunc = Callable[[str], Any]  # Used to parse a user input value
ParserRegistry = dict[type, ParserFunc]  # Stores value parsers
