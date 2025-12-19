from __future__ import annotations

from dataclasses import is_dataclass
from types import UnionType, NoneType
from typing import (
    Mapping,
    MutableMapping,
    Iterable,
    TypeVar,
    Any,
    get_origin,
    get_args,
    Protocol,
    Union,
)

from dc_input._types import GraphStart


class HasPrev(Protocol):
    prev: HasPrev


class HasNext(Protocol):
    next: HasNext


T = TypeVar("T")
U = TypeVar("U")
V = TypeVar("V", bound=HasPrev)
W = TypeVar("W", bound=HasNext)


def rgetitem(d: Mapping[T, U], ks: Iterable[T]) -> U:
    """Get item through an iterable of keys."""
    tmp = d
    for k in ks:
        tmp = tmp[k]

    return tmp


def rsetitem(d: MutableMapping[T, U], ks: Iterable[T], v: U) -> None:
    """Set item through an iterable of keys."""
    ks = list(ks)
    tmp = d
    for i, k in enumerate(ks):
        if i == len(ks) - 1:
            tmp[k] = v
        else:
            if k not in tmp:
                tmp[k] = {}
            tmp = tmp[k]


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


def safe_issubclass(
    cls: type, class_or_tuple: type | UnionType | tuple[Any, ...]
) -> bool:
    """Prevent TypeError when cls is not an instance of type"""
    return isinstance(cls, type) and issubclass(cls, class_or_tuple)


def is_node(t: type) -> bool:
    base, args = get_type_base_args(t)
    return is_dataclass(base) or base is GraphStart or find_schema_in_type_args(args)


def find_schema_in_type_args(args: tuple) -> type | None:
    for arg in args:
        # Direct schema
        if is_dataclass(arg):
            return arg

        base, sub_args = get_type_base_args(arg)

        # Union / Optional
        if base in (Union, UnionType):
            non_none = [a for a in sub_args if a is not NoneType]
            if non_none:
                found = find_schema_in_type_args(tuple(non_none))
                if found:
                    return found

        # Containers: tuple, list, set, etc.
        elif sub_args:
            found = find_schema_in_type_args(sub_args)
            if found:
                return found

    return None


def get_optional_non_none(t: UnionType) -> type:
    base, args = get_type_base_args(t)
    assert base is UnionType
    non_none = [a for a in args if a is not NoneType]

    return non_none[0]

def head(obj: V) -> V:
    res = obj
    while res.prev:
        res = res.prev
    return res


def tail(obj: W) -> W:
    res = obj
    while res.next:
        res = res.next
    return res
