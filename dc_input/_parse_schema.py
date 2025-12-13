from __future__ import annotations

from collections import defaultdict
from dataclasses import fields, is_dataclass, MISSING
from types import UnionType, NoneType
from typing import Any, TypeVar, get_type_hints, Union, Annotated, get_origin, get_args

from dc_input._errors import SchemaError, InternalError
from dc_input._types import KeyPath, SchemaDict, MetadataDict, Metadata, NestedSchema
from dc_input._utils import rsetitem, get_type_base_args

T = TypeVar("T")


def _validate_schema(sc: Any) -> None:
    if not is_dataclass(sc):
        raise SchemaError("Schema must be a dataclass")

    for name, t in get_type_hints(sc).items():
        if is_dataclass(t):
            _validate_schema(t)

        base, args = get_type_base_args(t)
        if base in (Union, UnionType):
            if NoneType not in args:
                raise SchemaError(
                    f"Ambiguous Union types {args}; only Optional[T] is allowed."
                )

            non_none = [a for a in args if a is not NoneType]
            if len(non_none) != 1:
                raise SchemaError(
                    f"Optional must contain exactly one non-None type; got {args}"
                )


def parse_schema(
    sc: Any,
    _path: KeyPath = (),
    _sc_dict: SchemaDict | None = None,
    _mdata_dict: MetadataDict | None = None,
) -> tuple[SchemaDict, MetadataDict]:
    _validate_schema(sc)

    _sc_dict = _sc_dict or defaultdict(dict)
    _mdata_dict = _mdata_dict or {}
    type_hints = get_type_hints(sc)
    flds = fields(sc)

    nodes: list[Metadata] = []
    for name, t in type_hints.items():
        fld = next(f for f in flds if f.name == name)
        mdata = Metadata(
            name=name,
            type=t,
            default=fld.default,
            default_factory=fld.default_factory,
        )

        # Restore annotation if necessary (get_type_hints strips annotations)
        fld_t_origin = get_origin(fld.type)
        if fld_t_origin is Annotated or (
            isinstance(fld_t_origin, str) and "Annotated" in fld_t_origin
        ):
            mdata.annotation = get_args(fld_t_origin)[1]

        # Tag NestedSchema if necessary
        if nested_schema := _find_schema_in_type(t):
            mdata.type = NestedSchema(inner_t=t, schema=nested_schema)
            nodes.append(mdata)
        else:
            path_new = _path + (name,)
            rsetitem(_sc_dict, path_new, MISSING)
            _mdata_dict[path_new] = mdata

    # For better query flow, move to next node after all leaves of current node are found
    for mdata in nodes:
        if not isinstance(mdata.type, NestedSchema):
            raise InternalError("Node must be instance of NestedSchema.")

        path_new = _path + (mdata.name,)
        _, t_args = get_type_base_args(mdata.type)
        schema_nested = mdata.type.schema
        _mdata_dict[path_new] = mdata

        rsetitem(_sc_dict, path_new, {})
        parse_schema(schema_nested, path_new, _sc_dict, _mdata_dict)

    return _sc_dict, _mdata_dict


def _find_schema_in_type(t: type) -> type | None:
    base, args = get_type_base_args(t)
    if is_dataclass(base):
        return base
    for arg in args:
        if is_dataclass(arg):
            return arg
    for arg in args:
        return _find_schema_in_type(arg)


def dict_to_dataclass_instance(cls: type[T], sc_dict: SchemaDict) -> T:
    if not is_dataclass(cls):
        raise InternalError("cls must be a dataclass type")

    kwargs = {}
    for name, t in get_type_hints(cls).items():
        v = sc_dict.get(name)
        if is_dataclass(t):
            v = dict_to_dataclass_instance(t, v)
        kwargs[name] = v
    return cls(**kwargs)
