from __future__ import annotations

from dataclasses import dataclass, field, MISSING
from types import UnionType
from typing import Annotated, TypeVar, Any

from dc_input._parse_schema import parse_schema
from dc_input._parse_value import parse_input
from dc_input._parsers import get_default_registry
from dc_input._types import (
    ParserRegistry,
    KeyPath,
    UserInput,
    ContainerRegistry,
    GraphEnd,
    GraphStart,
    QueryGraphPart,
    Node,
    Leaf,
)
from dc_input._utils import (
    get_type_base_args,
    alt_issubclass,
    head,
)
from dc_input._validate import validate

GREEN = "\033[32m"
GREY = "\033[90m"
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

    graph_head = parse_schema(schema, containers)
    parsers = get_default_registry() | parsers
    result = _get_input_result(graph_head, parsers)

    return head(result)


def _get_input_result(
    part_cur: QueryGraphPart,
    parsers: ParserRegistry,
    _res: list[UserInput] | None = None,
) -> UserInput:
    _res = _res or []

    match part_cur:
        case GraphStart():
            print(_format_node_header(part_cur.name))
            return _get_input_result(part_cur.next, parsers, _res)
        case GraphEnd():
            for v in _res:
                print(v)
            return _res[0]
        case Node():
            if skip_target := part_cur.skip_target:
                part_cur_fmt = f"[{_normalize_name(part_cur.name)}]"
                part_parent_fmt = f"[{_normalize_name(part_cur.parent.name)}]"
                if not _ask_yes_no(
                    f"\n> Add {part_cur_fmt} to {part_parent_fmt}? (y/n): "
                ):
                    return _get_input_result(skip_target, parsers, _res)

            header = _format_node_header(
                (part_cur.parent.name, part_cur.name), part_cur.repeat_n
            )
            if node_annotation := part_cur.annotation:
                annotation_fmt = f"\n{_format_node_annotation(node_annotation)}"
            else:
                annotation_fmt = ""
            print(f"\n{header}{annotation_fmt}")

            return _get_input_result(part_cur.next, parsers, _res)
        case Leaf():
            query = _format_leaf_query(part_cur)
            v_input = input(query).strip()

            # Special cases
            if v_input == "":
                if part_cur.is_optional:
                    _res.append(UserInput(None, part_cur))
                elif any(
                    v is not MISSING
                    for v in (part_cur.default, part_cur.default_factory)
                ):
                    v = (
                        part_cur.default
                        if part_cur.default is not MISSING
                        else part_cur.default_factory()
                    )
                    _res.append(UserInput(v, part_cur))
                else:
                    print(_format_input_error("must provide input"))
                    return _get_input_result(part_cur, parsers, _res)
            elif v_input == "..":
                if not _res:
                    print(_format_input_error("can't go to previous input"))
                    return _get_input_result(part_cur, parsers, _res)

                input_to_undo = _res.pop()
                part_undo = input_to_undo.graph_part
                if part_undo.parent != part_cur.parent:
                    if isinstance(part_undo.parent, GraphStart):
                        header = _format_node_header(part_undo.parent.name)
                    else:
                        header = _format_node_header(
                            (part_undo.parent.parent.name, part_undo.parent.name),
                            part_undo.parent.repeat_n,
                        )
                    print(f"\n{header}\n")

                return _get_input_result(part_undo, parsers, _res)
            else:
                # Normal cases
                try:
                    v_parsed = parse_input(v_input, part_cur.type, parsers)
                except AssertionError:
                    raise
                except Exception as e:
                    print(_format_input_error(e))
                    return _get_input_result(part_cur, parsers, _res)
                else:
                    _res.append(UserInput(v_parsed, part_cur))

            if repeat_entry := part_cur.repeat_entry:
                parent_cur_fmt = f"[{_normalize_name(part_cur.parent.name)}]"
                parent_parent_cur_fmt = (
                    f"[{_normalize_name(part_cur.parent.parent.name)}]"
                )
                if _ask_yes_no(
                    f"\n> Add another {parent_cur_fmt} to {parent_parent_cur_fmt}? (y/n): "
                ):
                    return _get_input_result(repeat_entry, parsers, _res)

            return _get_input_result(part_cur.next, parsers, _res)


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


def _format_node_header(
    schema_names: str | tuple[str, ...], repeat_n: tuple[int, int] = ()
) -> str:
    schema_names = (schema_names,) if isinstance(schema_names, str) else schema_names
    names_fmt = [_normalize_name(name) for name in schema_names]
    names_fmt = " -> ".join(name for name in names_fmt)

    repeat_n_fmt = ""
    if repeat_n:
        repeat_n_fmt = f" {repeat_n[0]} of {repeat_n[1]}"

    return f"[{names_fmt}{repeat_n_fmt}]"


def _format_node_annotation(annotation: str) -> str:
    return f"{GREY}# {annotation}{RESET}"


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


def _format_leaf_query(part: Leaf) -> str:
    name_fmt = _normalize_name(part.name)
    if part.is_optional:
        name_fmt += "?"

    input_hint = []
    if t_fmt := _format_type_hint(part.type):
        input_hint.append(t_fmt)
    if annotation := part.annotation:
        input_hint.append(annotation)
    input_hint_fmt = f" <{': '.join(input_hint)}>" if input_hint else ""

    v_def_fmt = "" if part.default is MISSING else f" (default: {part.default})"

    return f"{name_fmt}{input_hint_fmt}{v_def_fmt} : "


def _format_type_hint(t: type) -> str:
    base, args = get_type_base_args(t)
    assert base not in (Annotated, UnionType)

    if alt_issubclass(base, str):
        return ""
    elif alt_issubclass(base, dict):
        dict_args = ["str" if arg is Any else arg.__name__ for arg in args]
        dict_args.extend("str" for _ in range(2 - len(dict_args)))
        return f"({', '.join(dict_args)}), ..."
    elif alt_issubclass(base, (list, set)):
        assert len(args) <= 1
        if args:
            assert not alt_issubclass(args[0], dict)

        if not args:
            return "str, ..."
        elif alt_issubclass(args[0], (list, set, tuple)):
            return f"({_format_type_hint(args[0])}), ..."
        else:
            return f"{args[0].__name__}, ..."
    elif alt_issubclass(base, tuple):
        if not args:
            return "str, ..."

        args_fmt = []
        for arg in args:
            assert not alt_issubclass(arg, dict)
            if arg is Ellipsis:
                args_fmt.append("...")
            elif alt_issubclass(arg, str):
                args_fmt.append("str")
            elif alt_issubclass(arg, (list, set, tuple)):
                args_fmt.append(f"({_format_type_hint(arg)})")
            else:
                args_fmt.append(_format_type_hint(arg))
        return ", ".join(args_fmt)

    return t.__name__


@dataclass
class Hobby:
    name: str
    yrs_experience: int | None


@dataclass
class Student:
    name: str
    yrs_experience: Annotated[int | None, "round down"]
    hobbies: Annotated[list[Hobby], "Other stuff that the student likes to do"] = field(
        default_factory=list
    )


if __name__ == "__main__":
    get_input(Student)
