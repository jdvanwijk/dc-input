from __future__ import annotations

from dataclasses import is_dataclass
from types import UnionType, NoneType
from typing import (
    Any,
    get_origin,
    get_args,
    Union,
    Annotated,
)

from dc_input._types import KeyPath


def alt_issubclass(
    cls: type, class_or_tuple: type | UnionType | tuple[Any, ...]
) -> bool:
    """
    A less strict version of issubclass from standard library:
    - Accept UnionTypes and parameterized types
    - Prevent throw TypeError when cls is not an instance of type (return False instead)
    """
    base, args = get_type_base_args(cls)
    if base is Annotated:
        base, args = get_type_base_args(args[0])

    if base is UnionType and NoneType in args:
        base = get_optional_non_none(cls)

    return isinstance(base, type) and issubclass(base, class_or_tuple)


def find_schema_in_type(t: type | UnionType) -> type | None:
    base, args = get_type_base_args(t)
    if base is Annotated:
        base, args = get_type_base_args(args[0])

    # Direct schema
    if is_dataclass(base):
        return t

    # UnionType
    if base in (Union, UnionType):
        non_none = get_optional_non_none(t)
        if found := find_schema_in_type(non_none):
            return found

    # List, Set, Tuple
    if alt_issubclass(base, (list, set, tuple)):
        for arg in args:
            if found := find_schema_in_type(arg):
                return found

    return None


def get_optional_non_none(t: type | UnionType) -> type:
    base, args = get_type_base_args(t)

    if base is Annotated:
        base, args = get_type_base_args(args[0])

    if base not in (Union, UnionType):
        return t

    if len(args) != 2 or NoneType not in args:
        raise ValueError(f"Not Optional[T]: {t}")

    non_none = [a for a in args if a not in (NoneType, None)]

    return non_none[0]


def get_type_base_args(t: Any) -> tuple[Any, tuple[Any, ...]]:
    """
    Normalize typing constructs to (base, args).
    - For typing origins, return (origin, args)
    - For bare classes, return (class, ())
    """
    origin = get_origin(t)
    if origin is not None:
        args = get_args(t)
        return origin, args
    else:
        return t, ()


def is_child_path(parent: KeyPath, child: KeyPath) -> bool:
    return parent != child and parent == child[: len(parent)]
