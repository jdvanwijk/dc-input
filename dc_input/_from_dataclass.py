from __future__ import annotations

from copy import deepcopy
from dataclasses import MISSING, is_dataclass, dataclass, _MISSING_TYPE
from types import UnionType, NoneType
from typing import Union, Annotated, TypeVar, get_origin, get_args

from dc_input._errors import ParserRegistryError, SchemaError, InternalError
from dc_input._parse_schema import dict_to_dataclass_instance, parse_schema
from dc_input._parse_input import get_default_registry, prepare_parsers, parse_input
from dc_input._types import (
    ParserRegistry,
    KeyPath,
    SchemaDict,
    MetadataDict,
    Metadata,
    NestedSchema,
)
from dc_input._utils import get_type_base_args, rgetitem, safe_issubclass, rsetitem

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

T = TypeVar("T")


def from_dataclass(
    schema: type[T], *, custom_parsers: ParserRegistry | None = None
) -> T:
    sc_dict, mdata = parse_schema(schema)
    paths = list(mdata)
    parsers = prepare_parsers(get_default_registry(), custom_parsers)
    _fill_sc_dict(sc_dict, mdata, paths, parsers)

    return dict_to_dataclass_instance(schema, sc_dict)
    # Final check if all input is correct
    # while True:
    #     print("\nNew data:")
    #     for i, path in enumerate(leaves):
    #         p_fmt = ".".join(k for k in path)
    #         t_fmt = mdata[path].type
    #         v_cur_fmt = str(_rgetitem(sc_dict, path))
    #
    #         print(f"[{i}] {p_fmt} ({t_fmt}): {v_cur_fmt}")
    #
    #     ch = input("\nChange value? (n / {index},{new_value}): ").strip()
    #     if ch.lower() == "n":
    #         break
    #     try:
    #         i, v_input = ch.split(",")
    #         p = leaves[int(i.strip())]
    #         t = mdata[p].type
    #         v_parsed = _parse_input(v_input.strip(), t, parsers)
    #         _rsetitem(sc_dict, p, v_parsed)
    #     except (IndexError, ValueError):
    #         print("> Invalid input.")
    #         continue
    #
    # return dict_to_schema_instance(schema, sc_dict)


def _fill_sc_dict(
    sc_dict: SchemaDict,
    mdata_dict: MetadataDict,
    paths: list[KeyPath],
    parsers: ParserRegistry,
    _i: int = 0,
) -> SchemaDict:
    path_cur = paths[_i]
    mdata = mdata_dict[path_cur]
    t_base, t_args = get_type_base_args(mdata.type)

    # Print newline at beginning of new node
    if _i > 0:
        path_prev = paths[_i - 1]
        if path_prev[:-1] != path_cur[:-1]:
            print()

    # If field is node, go to first leaf of the next node
    if is_dataclass(t_base) and not isinstance(mdata.type, NestedSchema):
        return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, _i + 1)

    # Handle nested schemas separately
    if isinstance(mdata.type, NestedSchema):
        return _handle_nested_schema(
            path_cur, mdata, sc_dict, mdata_dict, paths, parsers, _i
        )

    # ---------- Query user ----------
    query = _format_leaf_query(path_cur, mdata, sc_dict)
    v_input = input(query).strip()

    # Special case: input is ".." (go back to previous input)
    if v_input == "..":
        i_prev = _find_prev_leaf_i(paths, mdata_dict, _i)
        if i_prev is None:
            print(_format_input_error("can't go to previous input"))
            return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, _i)
        else:
            print(_format_info("Returning to previous input"))
            return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i_prev)

    # Special case: input is "" (take current or default value)
    if v_input == "":
        cur_v = rgetitem(sc_dict, path_cur)
        def_v = mdata.default
        def_fact_v = mdata.default_factory
        non_missing = [v for v in (cur_v, def_v, def_fact_v) if v is not MISSING]
        if non_missing:
            v_parsed = non_missing[0]
            if v_parsed == mdata.default_factory:
                v_parsed = non_missing[0]()
            rsetitem(sc_dict, path_cur, v_parsed)
            v_kind = "current" if v_parsed == cur_v else "default"
            print(_format_info(f"Using {v_kind} value: {v_parsed}"))

            if _i < len(paths) - 1:
                return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, _i + 1)
            return sc_dict

    # Handle other input: parse and add to sc_dict, move to next path
    try:
        v_parsed = parse_input(v_input, mdata.type, parsers)
    except (SchemaError, ParserRegistryError, InternalError):
        raise
    except Exception as e:
        print(_format_input_error(e))
        return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, _i)
    else:
        rsetitem(sc_dict, path_cur, v_parsed)

    if _i < len(paths) - 1:
        return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, _i + 1)
    return sc_dict


def _handle_nested_schema(
    path_cur: KeyPath,
    mdata_cur: Metadata,
    sc_dict: SchemaDict,
    mdata_dict: MetadataDict,
    paths: list[KeyPath],
    parsers: ParserRegistry,
    i: int,
):
    nested = mdata_cur.type
    t_base, t_args = None, None
    try:
        t_base, t_args = get_type_base_args(nested.inner_t)
    except AttributeError:
        raise InternalError(f"Can't process {mdata_cur.type}")

    next_node_i = _find_next_node_i(paths, i)

    # ---------- Handle Optional[Schema] ----------
    if (
        t_base in (Union, UnionType)
        and NoneType in t_args
        and any(is_dataclass(arg) for arg in t_args)
    ):
        query = f"\nProvide input for {mdata_cur.name}? (y/n/..): "
        v_input = input(query).strip().lower()
        if v_input not in ("y", "n", ".."):
            # Invalid input, try again
            print(_format_input_error("respond with 'y' or 'n'. '..'"))
            return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i)
        elif v_input == "..":
            i_prev = _find_prev_leaf_i(paths, mdata_dict, i)
            if i_prev is None:
                print(_format_input_error("can't go to previous input"))
                return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i)
            else:
                print(_format_info("Returning to previous input"))
                return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i_prev)
        elif v_input == "y":
            # Go to nested schema
            return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i + 1)
        else:
            # skip nested schema and child nodes
            print(_format_info(f"Skipping optional schema."))
            rsetitem(sc_dict, path_cur, None)   # If user partially filled nested schema
            if next_node_i == len(paths) - 1:
                return sc_dict
            return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, next_node_i)

    # ---------- Handle list[Schema], set[Schema], tuple[Schema, ...] ----------
    should_query = False
    if safe_issubclass(t_base, (list, set)):
        if len(t_args) == 1 and is_dataclass(t_args[0]):
            should_query = True
    elif safe_issubclass(t_base, tuple):
        if len(t_args) == 2 and is_dataclass(t_args[0]) and t_args[1] is Ellipsis:
            should_query = True

    # Collect input
    if should_query:
        query_res = []
        child_paths = _get_child_paths(path_cur, paths)
        sc_dict_nested, mdata_dict_nested = parse_schema(nested.schema)
        query = f"\nProvide input for {mdata_cur.name}? (y/n/..): "
        v_input = input(query).strip().lower()
        if v_input not in ("y", "n", ".."):
            print(_format_input_error("respond with 'y', 'n' or '..'"))
            return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i)
        elif v_input == "..":
            i_prev = _find_prev_leaf_i(paths, mdata_dict, i)
            if i_prev is None:
                print(_format_input_error("can't go to previous input"))
                return _fill_sc_dict(sc_dict_nested, mdata_dict_nested, child_paths, parsers, i)
            else:
                print(_format_info("Returning to previous input"))
                return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, i_prev)
        elif v_input == "n":
            print(_format_info(f"Skipping optional schema."))
            query_res = t_base()
        else:
            # Loop through child paths as often as the user wants
            while True:
                sc_dict_tmp = deepcopy(sc_dict_nested)
                query_res.append(
                    _fill_sc_dict(sc_dict_tmp, mdata_dict_nested, child_paths, parsers)
                )
                query = f"\nProvide input for additional {mdata_cur.name}? (y/n): "
                v_input = input(query).strip().lower()
                if v_input not in ("y", "n"):
                    print(_format_input_error("respond with 'y' or 'n'"))
                elif v_input == "n":
                    print(_format_info(f"Moving on to next node."))
                    break

            query_res = t_base(query_res)

        # Queries complete: add result to sc_dict
        rsetitem(sc_dict, path_cur, query_res)

        # Move to next node
        if next_node_i == len(paths) - 1:
            return sc_dict
        return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, next_node_i)

    # ---------- Handle fixed-length tuple[Schema] ----------
    if (
        safe_issubclass(t_base, tuple)
        and len(t_args) >= 1
        and all(is_dataclass(arg) for arg in t_args)
    ):
        # Collect input
        child_paths = _get_child_paths(path_cur, paths)
        n_required_nested = len(t_args)
        query_res = []
        sc_dict_nested, mdata_dict_nested = parse_schema(nested.schema)
        n = 0
        while n < n_required_nested:
            n += 1
            print(f"Provide input for {mdata_cur.name} [{n}/{n_required_nested}]")
            sc_dict_tmp = deepcopy(sc_dict_nested)
            query_res.append(
                _fill_sc_dict(sc_dict_tmp, mdata_dict_nested, child_paths, parsers)
            )

        # queries complete: add result to sc_dict
        query_res = t_base(query_res)
        rsetitem(sc_dict, path_cur, query_res)

        if next_node_i == len(paths) - 1:
            return sc_dict
        return _fill_sc_dict(sc_dict, mdata_dict, paths, parsers, next_node_i)

    raise InternalError(f"Can't process {nested}")

def _format_info(msg: str) -> str:
    msg = str(msg).strip()
    if msg.endswith("."):
        msg = msg[:-1]

    return f"{GREEN}> {msg}.{RESET}"


def _format_input_error(e: Exception | str) -> str:
    msg = str(e).strip()
    if msg.endswith("."):
        msg = msg[:-1]

    return f"{RED}> Invalid input: {msg}.{RESET}"


def _format_leaf_query(p: KeyPath, mdata: Metadata, sc_dict: SchemaDict) -> str:
    # When using deepcopy, MISSING is converted to _MISSING_TYPE()
    _is_missing = lambda x: x is MISSING or isinstance(x, _MISSING_TYPE)

    p_fmt = ".".join(k for k in p)
    if get_origin(mdata.type) is Annotated:
        args = get_args(mdata.type)
        t_fmt = f" ({args[0].__name__})"
        annotation_fmt = f" (annotation: {args[1]})"
    else:
        t_fmt = f" ({mdata.type.__name__})"
        annotation_fmt = ""

    if not _is_missing(mdata.default):
        v_def_fmt = f" (default: {mdata.default})"
    elif not _is_missing(mdata.default_factory):
        v_def_fmt = f" (default_factory: {mdata.default_factory.__name__})"
    else:
        v_def_fmt = ""

    v = rgetitem(sc_dict, p)
    if not _is_missing(v):
        v_cur_fmt = f" (current value: {v})"
    else:
        v_cur_fmt = ""

    return f"{p_fmt}{t_fmt}{annotation_fmt}{v_def_fmt}{v_cur_fmt} : "


def _get_child_paths(parent: KeyPath, paths: list[KeyPath]) -> list[KeyPath]:
    res: list[KeyPath] = []
    for path in paths:
        if path == parent:
            continue
        elif path[: len(parent)] == parent:
            res.append(path[len(parent) :])
    return res


def _find_next_node_i(paths: list[KeyPath], i: int):
    prev_node = paths[i]
    while True:
        if i == len(paths) - 1:
            return i
        next_path = paths[i + 1]
        if prev_node == next_path[: len(prev_node)]:
            i += 1
        else:
            return i


def _find_prev_leaf_i(
    paths: list[KeyPath], mdata_dict: MetadataDict, i: int
) -> int | None:
    i_prev = i - 1
    for i in range(i_prev, -1, -1):
        mdata = mdata_dict[paths[i]]
        if not is_dataclass(mdata.type):
            return i_prev
        else:
            i_prev -= 1


@dataclass
class C:
    inner_inner_val1: int

@dataclass
class B:
    inner_val1: int
    inner_val2: str
    inner_val3: tuple[C, C]


@dataclass
class A:
    outer_val1: str
    node: B | None
    outer_val2: float


print(from_dataclass(A))
