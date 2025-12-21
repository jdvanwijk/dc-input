from __future__ import annotations

from dataclasses import dataclass,field
from types import UnionType
from typing import Annotated, TypeVar

from dc_input._parse_schema import parse_schema
from dc_input._parse_value import parse_input
from dc_input._parsers import get_default_registry
from dc_input._types import (
    ParserRegistry,
    KeyPath,
    FieldMetadata,
    UserInput,
    InputResult,
    NotProvided,
    ContainerRegistry,
    GraphEnd,
)
from dc_input._utils import (
    get_type_base_args,
    safe_issubclass,
    find_schema_in_type_args,
    is_node,
    head,
    get_optional_non_none,
)
from dc_input._validate import validate

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


T = TypeVar("T")


def get_input(
    schema: type[T],
    *,
    parsers: ParserRegistry | None = None,
    containers: ContainerRegistry | None = None,
) -> T:
    parsers = parsers or {}
    containers = containers or {}
    
    validate(schema, parsers, containers)

    first_field = parse_schema(schema, containers)
    first_input = UserInput(field=first_field)
    parsers = get_default_registry() | parsers
    result = _get_input_result(first_input, parsers)

    return head(result)


def _get_input_result(input_cur: UserInput, parsers: ParserRegistry) -> UserInput:
    fld_cur = input_cur.field
    if isinstance(fld_cur, GraphEnd):
        return head(input_cur)
    base, args = get_type_base_args(fld_cur.type)

    # ---------- Handle nodes ----------
    if fld_cur.skip_to:
        # Begin optional node (T | None, list[T], tuple[T, ...], etc.)
        _, args = get_type_base_args(fld_cur.type)
        next_schema = find_schema_in_type_args(args).__name__
        should_skip = _ask_yes_no(
            f"\n> Provide input for {_format_node_header(next_schema)}? (y/n): "
        )
        if not should_skip:
            print("\n", _format_node_header(next_schema))

        next_field = fld_cur.next if not should_skip else fld_cur.skip_to
        next_input = UserInput(next_field, prev=input_cur)
        print(next_field)
        return _get_input_result(next_input, parsers)
    if is_node(fld_cur.type):
        print(f"\n{_format_node_header(fld_cur.name, fld_cur.repeat_n)}")
        input_cur.field = fld_cur.next
        return _get_input_result(input_cur, parsers)

    # ---------- Query user ----------
    query = _format_leaf_query(fld_cur)
    v_input = input(query).strip()

    # Special case: undo previous input
    if v_input == "..":
        if not input_cur.prev:
            print(_format_input_error("can't go to previous input"))
            return _get_input_result(input_cur, parsers)

        input_to_undo = input_cur.prev
        next_input = UserInput(input_to_undo.field)
        if link_with := input_to_undo.prev:
            next_input.prev = link_with
            link_with.next = next_input
        return _get_input_result(next_input, parsers)

    # Special case: choose default value
    if v_input == "":
        default = fld_cur.default
        default_factory = fld_cur.default_factory
        non_missing = [v for v in (default, default_factory) if v is not NotProvided]
        if not non_missing:
            print(_format_input_error("missing input"))
            return _get_input_result(input_cur, parsers)
        else:
            to_parse = non_missing[0]
            v_parsed = to_parse() if to_parse is default_factory else to_parse
            input_cur.value = v_parsed

            next_input = UserInput(fld_cur.next, prev=input_cur)
            input_cur.next = next_input

            return _get_input_result(next_input, parsers)

    # Normal case
    try:
        input_cur.value = parse_input(v_input, fld_cur.type, parsers)
    except AssertionError:
        raise
    except Exception as e:
        print(_format_input_error(e))
        return _get_input_result(input_cur, parsers)

    # ---------- Prepare next input ----------
    if fld_cur.repeat_from:
        # Last leaf of list[T], tuple[T, ...], etc.
        repeat_from_node = fld_cur.repeat_from.prev
        if _ask_yes_no(
            f"> Provide input for additional [{repeat_from_node.name}] (y/n)? "
        ):
            input_cur.next = UserInput(fld_cur.repeat_from, prev=input_cur)

    if not input_cur.next:
        input_cur.next = UserInput(input_cur.field.next, prev=input_cur)

    return _get_input_result(input_cur.next, parsers)


def _ask_yes_no(prompt: str) -> bool:
    while True:
        v = input(prompt).strip().lower()
        if v in ("y", "n"):
            return v == "y"
        print(_format_input_error("must be either 'y' or 'n'"))


def _format_input_error(e: Exception | str) -> str:
    msg = str(e).strip()
    if msg.endswith("."):
        msg = msg[:-1]

    return f"{RED}> Invalid input: {msg}.{RESET}"


def _format_node_header(name: str, repeat_n: tuple[int, int] = ()) -> str:
    name_fmt = _normalize_name(name)

    repeat_n_fmt = ""
    if repeat_n:
        repeat_n_fmt = f" {repeat_n[0]} of {repeat_n[1]}"

    return f"[{name_fmt}{repeat_n_fmt}]"


def _normalize_name(name: str) -> str:
    res: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper():
            if i == 0:  # Do not add space before beginning of Class name
                res.append(ch.lower())
            else:
                res.append(f" {ch.lower()}")
        elif ch == "_":
            res.append(" ")
        else:
            res.append(ch)

    return "".join(res)


def _format_leaf_query(f: FieldMetadata) -> str:
    _exists = lambda x: not x is NotProvided

    base, args = get_type_base_args(f.type)
    if base is UnionType:
        t = get_optional_non_none(f.type)
    elif base is Annotated:
        t = args[0]
    else:
        t = f.type

    name_fmt = _normalize_name(f.name)
    if (
        base is UnionType
        or safe_issubclass(t, (set, list, dict))
        or f.default_factory is not NotProvided
    ):
        name_fmt += "?"

    t_hint_fmt = ""
    if safe_issubclass(t, (set, list, dict)):
        t_hint_fmt = " |val1,val2,...|"
    elif not safe_issubclass(t, str):
        t_hint_fmt = f" |{t.__name__}|"

    annotation_fmt = ""
    if annotation := f.annotation:
        annotation_fmt = f" (annotation: {annotation})"

    v_def_fmt = ""
    if _exists(f.default):
        v_def_fmt = f" (default: {f.default})"

    return f"{name_fmt}{t_hint_fmt}{annotation_fmt}{v_def_fmt} : "


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


@dataclass
class Hobby:
    name: str
    yrs_experience: int | None


@dataclass
class Student:
    name: str
    yrs_experience: Annotated[int | None, "round down"]
    hobbies: list[Hobby] = field(default_factory=list)


print(get_input(Student))
# TODO: CANT ADD HOBBY