from __future__ import annotations

from dataclasses import dataclass, field, MISSING
from types import UnionType
from typing import Annotated, TypeVar, Any, Literal

from dc_input._parse_schema import parse_schema
from dc_input._parse_user_inputs import parse_user_inputs
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
from dc_input._utils import get_type_base_args, alt_issubclass
from dc_input._validate import validate

BLUE = "\033[36m"
GREEN = "\033[32m"
GREY = "\033[90m"
RED = "\033[31m"
WHITE_MUTED = "\033[37m"

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

    for res in result:
        print(res)
        print(res.graph_part.parent)
        print()
    return parse_user_inputs(schema, result)


def _get_input_result(
    part_cur: QueryGraphPart,
    parsers: ParserRegistry,
    _res: list[UserInput] | None = None,
) -> list[UserInput]:
    _res = _res or []

    match part_cur:
        case GraphStart():
            print(f"{GREY}# Type '..' to undo previous input{RESET}")
            print(f"{GREY}# Press 'enter' to skip fields marked with {BLUE}?{RESET}")
            print(f"\n{_format_node_header(part_cur)}")
            return _get_input_result(part_cur.next, parsers, _res)
        case GraphEnd():
            return _res
        case Node():
            if skip_target := part_cur.skip_target:
                cur_fmt = f"[{_normalize_name(part_cur.name)}]"
                parent_fmt = f"[{_normalize_name(part_cur.parent.name)}]"
                repeats_fmt = f" ({part_cur.repeat_n[1]})" if part_cur.repeat_n else ""
                query = _format_control_flow_query(
                    f"Add {cur_fmt}{repeats_fmt} to {parent_fmt}?"
                )
                if not _ask_yes_no(f"\n{query}"):
                    return _get_input_result(skip_target, parsers, _res)

            header = _format_node_header(part_cur)
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
                # User wants to skip optional or select default value
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
                # User wants to undo previous input
                if not _res:
                    print(_format_input_error("no previous input to undo"))
                    return _get_input_result(part_cur, parsers, _res)

                input_to_undo = _res.pop()
                part_undo = input_to_undo.graph_part
                if part_undo.parent != part_cur.parent:
                    print(f"\n{_format_node_header(part_cur.parent)}")

                return _get_input_result(part_undo, parsers, _res)
            else:
                # Normal case
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
                parent_fmt = f"[{_normalize_name(repeat_entry.parent.name)}]"
                grandparent_fmt = (
                    f"[{_normalize_name(repeat_entry.parent.parent.name)}]"
                )
                query = _format_control_flow_query(
                    f"Add another {parent_fmt} to {grandparent_fmt}?"
                )
                if _ask_yes_no(f"\n{query}"):
                    header = _format_node_header(repeat_entry.parent)
                    print(f"\n{header}")
                    return _get_input_result(repeat_entry, parsers, _res)

            return _get_input_result(part_cur.next, parsers, _res)


def _ask_yes_no(prompt: str) -> bool:
    yes = "y"
    no = "n"
    while True:
        prompt_fmt = f"{prompt} <{yes}/{no}> : "
        v = input(prompt_fmt).strip().lower()
        if v in (yes, no):
            return v == yes
        print(_format_input_error(f"value must be '{yes}' or '{no}'"))


def _format_input_error(e: Exception | str) -> str:
    msg = str(e).strip()
    if msg.endswith("."):
        msg = msg[:-1]

    return f"{RED}> Invalid input: {msg}.{RESET}"


def _format_node_header(node: GraphStart | Node) -> str:
    assert isinstance(node, (GraphStart, Node))

    location_cur = _normalize_name(node.name)
    if isinstance(node, Node):
        location_cur = (
            f"{WHITE_MUTED}{_normalize_name(node.parent.name)} ->{RESET} {location_cur}"
        )

    repeat_n_fmt = ""
    if isinstance(node, Node) and node.repeat_n:
        repeat_n_fmt = f" {node.repeat_n[0]} of {node.repeat_n[1]}"

    return f"[{location_cur}{repeat_n_fmt}]"


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
        name_fmt += f"{BLUE}?{RESET}"

    input_hint = []
    if t_fmt := _format_type_hint(part.type):
        input_hint.append(t_fmt)
    if annotation := part.annotation:
        input_hint.append(annotation)
    input_hint_fmt = f" <{': '.join(input_hint)}>" if input_hint else ""

    v_def_fmt = (
        "" if part.default is MISSING else f"{GREY}(default: {part.default}){RESET} "
    )

    return f"{name_fmt}{input_hint_fmt} : {v_def_fmt}"


def _format_control_flow_query(query: str) -> str:
    return f"{GREEN}>{RESET} {query}"


def _format_type_hint(t: type) -> str:
    base, args = get_type_base_args(t)
    assert base not in (Annotated, UnionType)

    if base is Literal:
        return "/".join(str(arg) for arg in args)
    elif alt_issubclass(base, str):
        return ""
    elif alt_issubclass(base, bool):
        return "y/n"
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
class Inner:
    test: str


@dataclass
class Hobby:
    name: str
    yrs_experience: int | None
    inner: Inner


@dataclass
class Student:
    yrs_experience: Annotated[int | None, "round down"]
    name: str = field(default="petertje")
    hobbies: Annotated[
        list[Hobby] | None, "Other stuff that the student likes to do"
    ] = field(default_factory=list)


if __name__ == "__main__":
    get_input(Student)
