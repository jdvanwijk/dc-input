from __future__ import annotations

from types import UnionType
from typing import Mapping, MutableMapping, Iterable, TypeVar, Any, get_origin, get_args


T = TypeVar("T")
U = TypeVar("U")


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


