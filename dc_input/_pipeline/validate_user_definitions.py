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

from dc_input._types import ContainerAliasRegistry, ParserRegistry, KeyPath
from dc_input._pipeline._utils import (
    alt_issubclass,
    get_type_base_args,
    find_schema_in_type,
    get_optional_non_none,
)


def validate_user_definitions(
    schema: Any,
    container_aliases: ContainerAliasRegistry,
    parsers: ParserRegistry,
) -> None:
    """
    Validate the user-provided schema and all user-provided registries used by the input system.

    All detected issues are aggregated and raised as a single ValueError
    to provide a comprehensive error report to the user.

    Examples
    --------
    **Bad schema**::

        @dataclass
        class Inner:
            arg: str

        @dataclass
        class EmptySchema:
            pass

        class NotDataclass:
            pass

        @dataclass
        class BadSchema:
            not_dataclass: NotDataclass
            empty: EmptySchema
            none: None
            nested_annotation: list[Annotated[str, "hello"]]
            nested_union: list[str | None]
            ambiguous_union: str | int
            also_ambiguous: str | int | None
            dict_with_schema: dict[str, Inner]
            dict_with_dict: dict[int, dict]
            dict_with_container: dict[str, list]
            too_deep: list[list[list[str]]]
            also_too_deep: list[list[Inner]]
            container_with_dict: list[dict[str, int]]
            not_hashable: set[Inner]
            not_homogenuous: tuple[str, Inner]
            not_enough_schemas: tuple[Inner]
    """
    # Collect errors
    all_errors = {
        "container_aliases": _get_container_registry_errors(container_aliases),
        "parsers": _get_parser_registry_errors(parsers),
        "schema": _get_schema_errors(schema),
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


def _get_container_registry_errors(registry: ContainerAliasRegistry) -> list[str]:
    """
    Validate a container registry mapping custom container types to
    concrete substitute container implementations.

    Enforced rules:
    - Registry must be a dict
    - Keys and values must be concrete types

    Further rules for values:
    - Values must be subclasses of dict, list, set, or tuple (parameterized allowed).
    - Values can't be None
    - Unions:
        * only T | None unions are allowed (other Unions are ambiguous when parsing)
        * nested unions are not allowed (example: list[T | None])
    - Dicts:
        * may not contain nested schemas
        * may not contain nested dicts, lists, sets, tuples
    - List/Set/Tuple:
        * may only nest one level (example: list[list[T]]). exception: nesting is not allowed when T is a schema
        * may not contain nested dicts
    - Set:
        * schemas contained in a set must be hashable (frozen=True)
    - Fixed-size Tuple containing schemas:
        * must be homogenuous
        * must contain at least two schemas (user should use T instead of tuple[T])


    Returns a list of error messages describing all detected violations.
    """
    errors: list[str] = []

    if not isinstance(registry, dict):
        errors.append(f"Registry must be subclass of dict")
        return errors

    for container_t, alias_t in registry.items():
        alias_base, _ = get_type_base_args(alias_t)

        if not isinstance(container_t, type):
            errors.append(
                f"Registry keys must be concrete types [key: '{type(container_t).__name__}']"
            )
            continue

        if not isinstance(alias_base, type):
            errors.append(
                f"Registry values must be concrete types or parameterized types [key: '{container_t.__name__}', value: '{alias_t}']"
            )
            continue

        _, container_t_args = get_type_base_args(container_t)
        if container_t_args:
            errors.append(
                f"Parameterized registry keys are not allowed [key: '{container_t}]"
            )

        if not alt_issubclass(alias_base, (dict, list, set, tuple)):
            errors.append(
                f"Registry values must be subclass of dict, list, set or tuple "
                f"[key: '{container_t.__name__}', value: '{alias_t.__name__}']"
            )

        new_errors = _get_type_errors(alias_t)
        new_errors_fmt = [
            f"{err.strip()} [key: '{container_t.__name__}', value: '{alias_t.__name__}']"
            for err in new_errors
        ]
        errors.extend(new_errors_fmt)

    return errors


def _get_parser_registry_errors(registry: ParserRegistry) -> list[str]:
    """
    Validate a parser registry mapping concrete leaf types to parser functions.

    Enforced rules:
    - Registry must be a dict
    - Keys must be concrete types
    - Parsers must be callable
    - Parsers may not override primitive, container, union, or typing abstraction types

    Returns a list of error messages describing all detected violations.
    """

    invalid_types = {
        Annotated,
        Any,
        bool,
        dict,
        Dict,
        float,
        int,
        list,
        List,
        Literal,
        None,
        NoneType,
        set,
        Set,
        str,
        tuple,
        Tuple,
        Union,
        UnionType,
    }

    errors: list[str] = []

    if not isinstance(registry, dict):
        errors.append(f"Registry must be subclass of dict")
        return errors

    for t, parser in registry.items():
        if not isinstance(t, type):
            errors.append(f"Registry keys must be concrete types [key: '{type(t).__name__}']")
            continue

        if not callable(parser):
            errors.append(f"Parser not callable [key: '{t.__name__}']")

        base, args = get_type_base_args(t)
        if base in invalid_types:
            errors.append(
                f"Not allowed to override parser for type '{base.__name__}'. [key: '{t.__name__}'"
            )
        if args:
            errors.append(f"Parameterized types are not allowed [key: '{t.__name__}']")

    return errors


def _get_schema_errors(sc: Any, _errors: list[str] | None = None) -> list[str]:
    """
    Enforced rules:
    - Schema:
        * must be a dataclass
        * must have at least one field
        * field type can't be None
        * nested Annotations not allowed (example: list[Annotated[T]])
    - Unions:
        * only T | None unions are allowed (other Unions are ambiguous when parsing)
        * nested unions are not allowed (example: list[T | None])
    - Dicts:
        * may not contain nested schemas
        * may not contain nested dicts, lists, sets, tuples
    - List/Set/Tuple:
        * may only nest one level (example: list[list[T]]). exception: nesting is not allowed when T is a schema
        * may not contain nested dicts
    - Set:
        * schemas contained in a set must be hashable (frozen=True)
    - Fixed-size Tuple containing schemas:
        * must be homogenuous
        * must contain at least two schemas (user should use T instead of tuple[T])
    """
    if _errors is None:
        _errors = []

    # TODO [LOW]: The two checks below do not catch errors in inner schemas
    if not is_dataclass(sc):
        _errors.append(f"Schema must be a dataclass [schema: {sc.__name__}]")
    elif not fields(sc):
        _errors.append(f"Schema must have at least one field [schema: {sc.__name__}]")

    for name, t in get_type_hints(sc, include_extras=True).items():
        base, args = get_type_base_args(t)

        if t is NoneType:
            _errors.append(f"Type can't be NoneType [schema: {sc.__name__}, field: '{name}']")

        if args:
            for arg in args:
                base_inner, _ = get_type_base_args(arg)
                if base_inner is Annotated:
                    _errors.append(
                        f"Nested Annotations are not allowed [schema: {sc.__name__}, field: '{name}']"
                    )
                    continue

    for name, t in get_type_hints(sc).items():
        _, args = get_type_base_args(t)

        # Recursively validate nested schemas
        for arg in args:
            if nested := find_schema_in_type(arg):
                _get_schema_errors(nested, _errors)

        new_errors = _get_type_errors(t)
        new_errors_fmt = [
            f"{err.strip()} [schema: {sc.__name__}, field: '{name}']"
            for err in new_errors
        ]
        _errors.extend(new_errors_fmt)

    return _errors


def _get_type_errors(t: type) -> list[str]:
    errors: list[str] = []

    base, args = get_type_base_args(t)
    if not args:
        return errors

    # Reject None
    if t is NoneType:
        errors.append(f"Type can't be NoneType")
        return errors

    # UnionType
    if _has_union_in_args(t):
        errors.append(f"Nested UnionTypes are not allowed")
        return errors

    if base in (Union, UnionType):
        if NoneType not in args:
            errors.append(
                f"Ambiguous Union types are not allowed; only T | None is allowed "
            )
            return errors

        non_none = [a for a in args if a is not NoneType]
        if len(non_none) != 1:
            errors.append(f"T | None must contain exactly one non-None type")
            return errors

    # list, set, tuple[T, ...]
    if alt_issubclass(t, (list, set, tuple)):
        depth = _max_container_depth(t)
        if depth > 2:
            errors.append(
                f"Containers may only nest one level deep; got nesting depth {depth} "
                f"(Hint: a nested schema is also considered a nesting level) "
            )

        t_to_check = get_optional_non_none(t) if base is UnionType else t
        base_to_check, args_to_check = get_type_base_args(t_to_check)
        if alt_issubclass(base_to_check, (list, set, tuple)):
            if args_to_check and alt_issubclass(args_to_check[0], dict):
                errors.append(f"Lists, sets and tuples may not contain nested dicts")

    if alt_issubclass(t, set):
        sc_nested = find_schema_in_type(t)
        assert hasattr(sc_nested, "__dataclass_params__")
        if sc_nested and not sc_nested.__dataclass_params__.frozen:
            errors.append(
                f"Schemas contained in sets must be frozen dataclasses "
                f"(Hint: set frozen=True in the dataclass constructor)"
            )

    # dict
    if alt_issubclass(t, dict):
        if any(find_schema_in_type(arg) for arg in args):
            errors.append(f"Dicts can't contain nested schemas")
        for dict_param in args:
            base, _ = get_type_base_args(dict_param)
            if alt_issubclass(base, (dict, list, set, tuple)):
                errors.append(
                    f"Dicts can't contain nested dicts, lists, sets or tuples"
                )

    # Fixed-size tuples containing schemas
    if alt_issubclass(t, tuple) and find_schema_in_type(t) and Ellipsis not in args:
        if not all(is_dataclass(arg) for arg in args):
            errors.append(
                f"Tuple can't contain both schemas and other types "
                f"(Hint: give each tuple arg its own field in a parent schema)"
            )
            return errors
        if len(args) < 2:
            errors.append(
                f"Fixed-size tuple must contain at least two schemas "
                f"(Hint: use T instead of tuple[T])"
            )
        if not all(arg == args[0] for arg in args):
            errors.append(
                f"All schemas in a tuple must have a single type "
                f"(Hint: give each tuple arg its own field in a parent schema)"
            )

    return errors


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

    # Add one to depth when nested schema
    if is_dataclass(base):
        return 1

    return 0


def _has_union_in_args(t: type | UnionType) -> bool:
    def _has_nested_union(x) -> bool:
        base, args = get_type_base_args(x)
        if base in (Union, UnionType):
            return True
        return any(_has_nested_union(a) for a in args)

    _, args = get_type_base_args(t)
    return any(_has_nested_union(a) for a in args)


if __name__ == "__main__":
    @dataclass
    class Inner:
        arg: str


    @dataclass
    class EmptySchema:
        pass


    class NotDataclass:
        pass


    @dataclass
    class BadSchema:
        not_dataclass: NotDataclass
        empty: EmptySchema
        none: None
        nested_annotation: list[Annotated[str, "hello"]]
        deprecated: Optional[str]
        nested_union: list[str | None]
        ambiguous_union: str | int
        also_ambiguous: str | int | None
        dict_with_schema: dict[str, Inner]
        dict_with_dict: dict[int, dict]
        dict_with_container: dict[str, list]
        too_deep: list[list[list[str]]]
        also_too_deep: list[list[Inner]]
        container_with_dict: list[dict[str, int]]
        not_hashable: set[Inner]
        not_homogenuous: tuple[str, Inner]
        not_enough_schemas: tuple[Inner]

    validate_user_definitions(BadSchema, {}, {})

    # TODO [LOW]: add bad parser registry and bad container aliases registry examples
