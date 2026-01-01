from collections.abc import Iterable
from dataclasses import is_dataclass, fields, dataclass
from types import NoneType, UnionType
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Set,
    Tuple,
    Union,
    get_type_hints,
    Optional,
)

from dc_input._types import ContainerRegistry, NonSchemaRegistry, ParserRegistry
from dc_input._utils import (
    alt_issubclass,
    get_type_base_args,
    find_schema_in_type,
    get_optional_non_none,
)


def validate_user_definitions(
    schema: Any,
    containers: ContainerRegistry,
    non_schemas: NonSchemaRegistry,
    parsers: ParserRegistry,
) -> None:
    """
    Validate the user-provided schema and all user-provided registries used by the input system.

    All detected issues are aggregated and raised as a single ValueError
    to provide a comprehensive error report to the user.
    """
    # Collect errors
    all_errors = {
        "containers": _get_container_registry_errors(containers),
        "non_schemas": _get_non_schema_registry_errors(non_schemas),
        "parsers": _get_parser_registry_errors(parsers),
    }

    if not all_errors["non_schemas"]:
        all_errors["schema"] = _get_schema_errors(schema, non_schemas)

    # Format errors
    fmt = lambda err: f"- {err}\n"
    res: list[str] = []
    for kind, errors in all_errors.items():
        if errors:
            res.append(f"\nInvalid {kind}:\n")
            res.extend(fmt(err) for err in errors if fmt(err) not in res)

    if res:
        raise ValueError("".join(res))


def _get_container_registry_errors(registry: ContainerRegistry) -> list[str]:
    """
    Validate a container registry mapping custom container types to
    concrete substitute container implementations.

    Enforced rules:
    - Registry must be a dict.
    - Keys must be concrete, non-parameterized types.
    - Values must be concrete subclasses of dict, list, set, or tuple.

    Returns a list of error messages describing all detected violations.
    """
    errors: list[str] = []

    if not isinstance(registry, dict):
        errors.append(
            f"Registry must be subclass of dict, got '{type(registry).__name__}'"
        )
        return errors

    for container_t, substitute_t in registry.items():
        if not isinstance(container_t, type):
            errors.append(f"Registry keys must be concrete types, got '{container_t}'")
            continue
        if not isinstance(substitute_t, type):
            errors.append(
                f"Registry values must be concrete types, got '{substitute_t}' at key '{container_t}'"
            )
            continue

        _, container_t_args = get_type_base_args(container_t)
        if container_t_args:
            errors.append(
                f"Parameterized registry keys are not allowed, got '{container_t}'"
            )

        substitue_t_base, _ = get_type_base_args(substitute_t)
        if not alt_issubclass(substitue_t_base, (dict, list, set, tuple)):
            errors.append(
                f"Registry values must be subclasses of dict, list, set or tuple, got "
                f"'{substitute_t}' at key '{container_t}'"
            )

    return errors


def _get_non_schema_registry_errors(registry: NonSchemaRegistry) -> list[str]:
    """
    Validate the non-schema registry, which declares types that should
    be treated as leaf values rather than nested schemas.

    Enforced rules:
    - Registry must be iterable.
    - All entries must be concrete types.
    - Parameterized types are not allowed.

    Returns a list of error messages describing all detected violations.
    """
    errors: list[str] = []

    if not isinstance(registry, Iterable):
        errors.append("Registry must be iterable")
        return errors

    for t in registry:
        if not isinstance(t, type):
            errors.append(f"Registry values must be concrete types, got '{t}'")
            continue
        _, args = get_type_base_args(t)
        if args:
            errors.append(f"Parameterized registry values are not allowed, got '{t}'")

    return errors


def _get_parser_registry_errors(registry: ParserRegistry) -> list[str]:
    """
    Validate a parser registry mapping concrete leaf types to parser functions.

    Enforced rules:
    - Registry must be a dict.
    - Keys must be concrete, non-parameterized types.
    - Parsers must be callable.
    - Parsers may not override container, union, or typing abstraction types
      (e.g. list, dict, Union, Annotated, Literal, Any, NoneType).
    - Parameterized types are not allowed as parser keys.

    Returns a list of error messages describing all detected violations.
    """

    invalid_types = {
        Annotated,
        Any,
        dict,
        Dict,
        list,
        List,
        Literal,
        None,
        NoneType,
        set,
        Set,
        tuple,
        Tuple,
        Union,
        UnionType,
    }

    errors: list[str] = []

    if not isinstance(registry, dict):
        errors.append(
            f"Registry must be subclass of dict, got '{type(registry).__name__}'"
        )
        return errors

    for t, parser in registry.items():
        if not isinstance(t, type):
            errors.append(f"Registry keys must be concrete types, got '{t}'")
            continue

        if not callable(parser):
            errors.append(
                f"Parser for type '{t.__name__}' is not callable (received: {parser})"
            )

        base, args = get_type_base_args(t)
        if base in invalid_types:
            errors.append(f"Not allowed to override parser for type '{base.__name__}'")
        if args:
            errors.append(f"Parameterized types are not allowed (received: '{t}'")

    return errors


def _get_schema_errors(
    sc: Any, non_schemas: NonSchemaRegistry, _errors: list[str] | None = None
) -> list[str]:
    """
    Enforced rules:
    - Schema:
        * must be a dataclass
        * must have at least one field
        * field type can't be None
        * fields may not have nested Annotations (list[Annotated[T]], etc.)
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

    for name, t in get_type_hints(sc, include_extras=True).items():
        base, args = get_type_base_args(t)

        if args:
            for arg in args:
                base_inner, _ = get_type_base_args(arg)
                if base_inner is Annotated:
                    _errors.append(
                        f"Nested Annotations are not allowed [schema: {sc.__name__}, field: '{name}']"
                    )
                    continue

    for name, t in get_type_hints(sc).items():
        base, args = get_type_base_args(t)

        if t in (None, NoneType):
            _errors.append(
                f"Field type can't be None [schema: {sc.__name__}, field: '{name}']"
            )

        # Recursively validate nested schemas
        for arg in args:
            if nested := find_schema_in_type(arg, non_schemas):
                _get_schema_errors(nested, _errors)

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

        # List, Set, Tuple[T, ...]
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
            if any(find_schema_in_type(arg, non_schemas) for arg in args):
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
        if alt_issubclass(t, tuple) and find_schema_in_type(t, non_schemas):
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
