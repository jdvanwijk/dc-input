from __future__ import annotations

from dataclasses import fields, is_dataclass, make_dataclass
from types import UnionType
from typing import Any, get_type_hints, Literal, Annotated, Union

from dc_input._types import (
    NormalizedSchema,
    ContainerAliasRegistry,
    KeyPath,
    SchemaShape,
    ContainerShape,
    NormalizedField,
    FixedSchemaContainerShape,
    FixedContainerShape,
    LiteralShape,
    DictShape,
    AtomicShape,
    SchemaContainerShape,
    ContextShape,
    InputShape,
)
from dc_input._pipeline._utils import (
    get_type_base_args,
    get_optional_non_none,
    alt_issubclass,
    find_schema_in_type,
)


# ------------------------------------------------------------
# Main function
# ------------------------------------------------------------
def normalize_schema(
    sc: Any,
    container_aliases: ContainerAliasRegistry,
    _path: KeyPath = (),
    _res: NormalizedSchema | None = None,
) -> NormalizedSchema:
    """
    Convert a user-facing schema (dataclasses + typing annotations)
    into a flat, uniform representation for downstream processing.

    Produce a mapping from a field path (a tuple of nested field names)
    to a 'NormalizedField'. Each 'NormalizedField' contains a 'FieldShape'. This is a
    structural description of how values are composed: leaf values, containers,
    fixed tuples with schemas, fixed tuples without schemas, dictionaries, literals,
    or nested schemas.

    Assumptions about the schema are based on validation done before in
    validate_user_definitions.py.
    """
    assert is_dataclass(sc)

    _res = _res or {}

    type_hints = get_type_hints(sc, include_extras=True)
    flds = fields(sc)
    for name, t in type_hints.items():
        fld_cur = next(fld for fld in flds if fld.name == name)
        if not fld_cur.init:
            continue

        path_cur = _path + (name,)

        default = fld_cur.default
        default_factory = fld_cur.default_factory

        t_no_annotation, annotation = _extract_annotation(t)
        base_no_annotation, _ = get_type_base_args(t_no_annotation)

        # Assume UnionType is T | None or Optional[T]
        is_optional = base_no_annotation in (Union, UnionType)

        # field_type: original type without annotation and UnionType
        if base_no_annotation in (Union, UnionType):
            field_type = get_optional_non_none(t_no_annotation)
        else:
            field_type = t_no_annotation

        # shape_type: field_type or alias type (alias type has priority)
        base_shape, args_shape = get_type_base_args(field_type)
        if alias := container_aliases.get(base_shape):
            alias_base, alias_args = get_type_base_args(alias)
            base_shape = alias_base
            # Alias is specific if alias_args (e.g. list[int]), else treat as generic
            if alias_args:
                args_shape = alias_args
        shape = _get_shape(base_shape, args_shape)

        _res[path_cur] = NormalizedField(
            path=path_cur,
            type_non_aliased=field_type,
            is_optional=is_optional,
            default=default,
            default_factory=default_factory,
            annotation=annotation,
            shape=shape,
        )

        type_to_check = base_shape[args_shape] if alias else field_type
        if sc_nested := find_schema_in_type(type_to_check):
            normalize_schema(sc_nested, container_aliases, path_cur, _res)

    return _res


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _extract_annotation(t: type) -> tuple[type | UnionType, str]:
    def _extract(t_with_annotation: type) -> str:
        base, args = get_type_base_args(t_with_annotation)
        if base is Annotated:
            return args[1]
        for arg in args:
            return _extract(arg)
        return ""

    to_process = make_dataclass("ToProcess", [("type", t)])
    t_without = get_type_hints(to_process)["type"]
    t_with = get_type_hints(to_process, include_extras=True)["type"]
    annotation = _extract(t_with)

    return t_without, annotation


def _get_shape(base: type, args: tuple[Any, ...]) -> ContextShape | InputShape:
    if is_dataclass(base):
        # SchemaShape
        return SchemaShape(base)
    elif base is Literal:
        # LiteralShape
        return LiteralShape(args)
    elif alt_issubclass(base, dict):
        # DictShape
        args = args + tuple(Any for _ in range(2 - len(args)))
        keys_t = AtomicShape(args[0])
        vals_t = AtomicShape(args[1])
        return DictShape(keys_t, vals_t)
    elif (
        alt_issubclass(base, (list, set))
        or Ellipsis in args
        or (alt_issubclass(base, tuple) and not args)
    ):
        # ContainerShape / SchemaContainerShape
        args = args or (Any,)
        base_inner, args_inner = get_type_base_args(args[0])
        if is_dataclass(base_inner):
            return SchemaContainerShape(base, base_inner)
        else:
            # Assume max depth == 2
            element = _get_shape(base_inner, args_inner)
            assert isinstance(
                element,
                (AtomicShape, ContainerShape, FixedContainerShape, LiteralShape),
            )
            return ContainerShape(base, element)
    elif alt_issubclass(base, tuple):
        # FixedContainerShape / FixedSchemaContainerShape
        args = args or (Any,)
        if is_dataclass(args[0]):
            # Assume homogeneous when schema in args
            return FixedSchemaContainerShape(base, args[0], len(args))
        else:
            elements = []
            for arg in args:
                # Assume max depth == 2
                base_inner, args_inner = get_type_base_args(arg)
                elements.append(_get_shape(base_inner, args_inner))
                assert all(
                    isinstance(
                        el,
                        (
                            AtomicShape,
                            ContainerShape,
                            FixedContainerShape,
                            LiteralShape,
                        ),
                    )
                    for el in elements
                )
            return FixedContainerShape(base, tuple(elements))
    else:
        return AtomicShape(base)
