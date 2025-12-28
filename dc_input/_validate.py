from __future__ import annotations

from dataclasses import is_dataclass, dataclass, fields
from types import UnionType, NoneType
from typing import Any, get_type_hints, Union, Annotated, Literal, TypeVar, Optional

from dc_input._types import ParserRegistry, ContainerRegistry
from dc_input._utils import (
    get_type_base_args,
    alt_issubclass,
    is_node,
    find_schema_in_type_args, get_optional_non_none,
)

T = TypeVar("T")


def validate(
    schema: Any, parsers: ParserRegistry, containers: ContainerRegistry
) -> None:
    # Collect errors
    all_errors = {
        "schema": _get_schema_errors(schema),
        "parsers": _get_parser_registry_errors(parsers),
        "containers": _get_parser_registry_errors(containers),
    }

    # Format errors
    fmt = lambda err: f"- {err}\n"
    res: list[str] = []
    for kind, errors in all_errors.items():
        if errors:
            res.append(f"\nInvalid {kind}:\n")
            res.extend(fmt(err) for err in errors if fmt(err) not in res)

    if res:
        raise ValueError("".join(res))


def _get_schema_errors(sc: Any, _errors: list[str] | None = None) -> list[str]:
    """
    Enforced rules:
    - Schema:
        * must be a dataclass
        * must have at least one field
        * field type can't be None
    - Unions:
        * only T | None unions are allowed (other Unions are ambiguous when parsing)
        * use of typing.Optional is not allowed (considered deprecated, adds parsing complexity)
    - List/Set/Tuple:
        * may only nest one level (ie: list[list] is okay, list[list[list]] isn't)
        * may not contain nested dicts
    - Dicts:
        * may not contain nested schemas
        * may not contain nested dicts, lists, sets, tuples
    - Fixed-size Tuple containing schemas:
        * must contain only schemas
        * must contain at least two schemas (user should use T instead of tuple[T])
        * must be homogeneous
    """
    if _errors is None:
        _errors = []

    if not is_dataclass(sc):
        _errors.append(f"Schema must be a dataclass [schema: {sc.__name__}]")
    elif not fields(sc):
        _errors.append(f"Schema must have at least one field [schema: {sc.__name__}]")

    for name, t in get_type_hints(sc).items():
        base, args = get_type_base_args(t)

        # Recursively validate nested schemas
        if nested := find_schema_in_type_args(args):
            _get_schema_errors(nested, _errors)

        # Reject None
        if t in (None, NoneType):
            _errors.append(f"Field type can't be None [schema: {sc.__name__}, field: '{name}']")

        # Union
        if base is Optional:
            _errors.append(
                f"Optional[T] is not allowed; use T | None instead [schema: {sc.__name__}, field: '{name}']"
            )
            continue
        if base in (Union, UnionType):
            if NoneType not in args:
                _errors.append(
                    f"Ambiguous Union types {args}; only T | None is allowed. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )
                continue

            non_none = [a for a in args if a is not NoneType]
            if len(non_none) != 1:
                _errors.append(
                    f"T | None must contain exactly one non-None type; got {args}. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )

        # List, Set, Tuple
        if alt_issubclass(t, (list, set, tuple)):
            depth = _max_container_depth(t)
            if depth > 2:
                _errors.append(
                    f"Containers may only nest one level deep; got nesting depth {depth}. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )

            t_to_check = get_optional_non_none(t) if base is UnionType else t
            base_to_check, args_to_check = get_type_base_args(t_to_check)
            if alt_issubclass(base_to_check, (list, set, tuple)):
                if args_to_check and alt_issubclass(args_to_check[0], dict):
                    _errors.append(
                        f"Lists, sets and tuples may not contain nested dicts. "
                        f"[schema: {sc.__name__}, field: '{name}']"
                    )

        # Dict
        if alt_issubclass(t, dict):
            if any(is_node(arg) for arg in args):
                _errors.append(
                    f"Dicts can't contain nested schemas; got {args}. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )
            for dict_param in args:
                base, _ = get_type_base_args(dict_param)
                if alt_issubclass(base, (dict, list, set, tuple)):
                    _errors.append(
                        f"Dicts can't contain nested dicts, lists, sets or tuples;"
                        f" got {args}. [schema: {sc.__name__}, field: '{name}']"
                    )

        # Fixed-size tuples containing schemas
        if alt_issubclass(t, tuple) and find_schema_in_type_args(args):
            if not all(is_dataclass(arg) for arg in args):
                _errors.append(
                    f"Tuple can't contain both schemas and other types; got {args}. "
                    f"(Hint: give each tuple arg its own field in a parent schema) "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )
                continue
            if len(args) < 2:
                _errors.append(
                    f"Fixed-size tuple must contain at least two schemas; got {args}. "
                    f"(Hint: use T instead of tuple[T]) "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )
            if not all(arg == args[0] for arg in args):
                _errors.append(
                    f"All schemas in a tuple must have a single type; got {args}. "
                    f"(Hint: give each tuple arg its own field in a parent schema) "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )

    return _errors


def _get_parser_registry_errors(registry: ParserRegistry) -> list[str]:
    errors: list[str] = []

    invalid_types = {
        Annotated,
        Any,
        dict,
        list,
        Literal,
        None,
        NoneType,
        set,
        tuple,
        Union,
        UnionType,
    }
    for t, parser in registry.items():
        base, _ = get_type_base_args(t)
        if not callable(parser):
            errors.append(
                f"Parser for type '{t.__name__}' is not callable (received: {parser})"
            )
        if base in invalid_types:
            errors.append(f"Not allowed to override parser for type '{base.__name__}'")
        if not isinstance(t, type):
            errors.append(f"Parser keys must be concrete types, got '{t}'")

    return errors


def _get_container_registry_errors(registry: ContainerRegistry) -> list[str]:
    # TODO: IMPLEMENT
    return []


def _max_container_depth(t: Any) -> int:
    base, args = get_type_base_args(t)

    # Unwrap Annotated
    if base is Annotated:
        return _max_container_depth(args[0])

    # Unwrap Optional / Union[T | None]
    if base in (Union, UnionType):
        non_none = [a for a in args if a is not NoneType]
        if len(non_none) == 1:
            return _max_container_depth(non_none[0])
        return 0

    # Container types
    if base in (list, set, tuple):
        if not args:
            return 1
        return 1 + max(_max_container_depth(arg) for arg in args)

    return 0


if __name__ == "__main__":

    @dataclass
    class Inner2:
        pass

    @dataclass
    class Inner:
        pass

    @dataclass
    class WrongSchema:
        a: int | str
        b: str | float | None
        c: dict[str, list]
        d: tuple[Inner, int]
        e: tuple[Inner]
        f: tuple[Inner, Inner2]
        g: Annotated[list[list[list[str]]], "too deep"]
        h: list | None

    wrong_parser_registry = {NoneType: "not a parser", "not a type": int}

    validate(WrongSchema, wrong_parser_registry, {})
