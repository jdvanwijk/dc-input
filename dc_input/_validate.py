from __future__ import annotations

from dataclasses import is_dataclass, dataclass
from types import UnionType, NoneType
from typing import Any, get_type_hints, Union, Annotated, Literal

from dc_input._types import ParserRegistry, ContainerRegistry
from dc_input._utils import (
    get_type_base_args,
    safe_issubclass,
    is_node,
    find_schema_in_type_args,
)


def validate(
    schema: Any, parsers: ParserRegistry, containers: ContainerRegistry
) -> None:
    schema_errors = [_format_err(err) for err in _get_schema_errors(schema)]
    parser_registry_errors = [
        _format_err(err) for err in _get_parser_registry_errors(parsers)
    ]
    container_registry_errors = [
        _format_err(err) for err in _get_container_registry_errors(containers)
    ]

    error_msg: list[str] = []
    if schema_errors:
        error_msg.append("Invalid schema:")
        error_msg.extend(schema_errors)
        error_msg.append("")
    if parser_registry_errors:
        error_msg.append("Invalid parser registry:")
        error_msg.extend(parser_registry_errors)
        error_msg.append("")
    if container_registry_errors:
        error_msg.append("Invalid container registry:")
        error_msg.extend(container_registry_errors)
        error_msg.append("")

    if error_msg:
        raise ValueError("\n".join(error_msg))


def _get_schema_errors(sc: Any, _errors: list[str] | None = None) -> list[str]:
    """
    Enforced rules:
    - Schema must be a dataclass.
    - Optional:
        * Only Optional[T] (T | None) unions are allowed (other Unions are ambiguous when parsing)
    - List/Set/Tuple:
        * may only nest one level (ie: list[list] is okay, list[list[list]] isn't)
    - Dicts:
        * may not contain nested schemas (prevent poor UX)
        * may not contain nested dicts, lists, sets, tuples (prevent poor UX)
    - Fixed-size Tuple containing schemas:
        * must contain only schemas (tuples mixing primitives and schemas cause poor UX)
        * must contain at least two schemas (user should use T instead of tuple[T])
        * must be homogeneous (mixed schema-tuples cause poor UX)
    """
    if _errors is None:
        _errors = []

    if not is_dataclass(sc):
        _errors.append("Schema must be a dataclass")

    for name, t in get_type_hints(sc).items():
        # Recursively validate nested schemas
        if is_dataclass(t):
            _get_schema_errors(t, _errors)

        base, args = get_type_base_args(t)

        # Union / Optional
        if base in (Union, UnionType):
            if NoneType not in args:
                _errors.append(
                    f"Ambiguous Union types {args}; only Optional[T] is allowed. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )
                continue

            non_none = [a for a in args if a is not NoneType]
            if len(non_none) != 1:
                _errors.append(
                    f"Optional must contain exactly one non-None type; got {args}. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )


        # List, Set, Tuple: check max depth
        if base in (list, set, tuple):
            depth = _max_container_depth(t)
            if depth > 2:
                _errors.append(
                    f"Containers may only nest one level deep; got nesting depth {depth}. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )

        # Dict
        if safe_issubclass(base, dict):
            if any(is_node(arg) for arg in args):
                _errors.append(
                    f"Dicts can't contain nested schemas; got {args}. "
                    f"[schema: {sc.__name__}, field: '{name}']"
                )
            for dict_param in args:
                base, _ = get_type_base_args(dict_param)
                if safe_issubclass(base, (dict, list, set, tuple)):
                    _errors.append(
                        f"Dicts can't contain nested dicts, lists, sets or tuples;"
                        f" got {args}. [schema: {sc.__name__}, field: '{name}']"
                    )

        # Fixed-size tuples containing schemas
        if base is tuple and find_schema_in_type_args(args):
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


def _format_err(err: str) -> str:
    return f"- {err}"


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
