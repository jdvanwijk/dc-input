from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, MISSING, _MISSING_TYPE
from typing import Union, Any


# ---------- Structs ----------
@dataclass
class Metadata:
    """Metadata of a schema field"""

    name: str
    type: type
    default: Any | _MISSING_TYPE = MISSING
    default_factory: Callable | _MISSING_TYPE = MISSING
    annotation: str = ""


@dataclass
class NestedSchema:
    """A tag signifying that inner_t should be treated as a nested schema"""

    inner_t: Any
    schema: type


# ---------- Type aliases ----------
KeyPath = tuple[str, ...]  # Path to a specific schema field
MetadataDict = dict[KeyPath, Metadata]  # Collects metadata of schema fields
SchemaDict = dict[str, Union["SchemaDict", Any]]  # Collects user input
ParserFunc = Callable[[str], Any]  # Used to parse a user input value
ParserRegistry = dict[type, ParserFunc]  # Stores value parsers

