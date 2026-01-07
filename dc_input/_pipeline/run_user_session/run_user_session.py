from dataclasses import MISSING
from typing import Any

from dc_input._pipeline.run_user_session._parse_input import parse_input
from dc_input._types import (
    SessionStart,
    ParserRegistry,
    UserInput,
    SessionStep,
    SessionEnd,
    ContextStep,
    InputStep,
    ContainerShape,
    DictShape,
    LiteralShape,
    AtomicShape,
    FixedContainerShape,
    NormalizedField,
    TerminalShape,
)
from dc_input._utils import get_type_base_args

BLUE = "\033[36m"
GREEN = "\033[32m"
GREY = "\033[90m"
RED = "\033[31m"

BOLD = "\033[1m"

RESET = "\033[0m"


def run_user_session(
    step_cur: SessionStep,
    parsers: ParserRegistry,
    _res: list[UserInput] | None = None,
) -> list[UserInput]:
    if _res is None:
        _res = []

    if isinstance(step_cur, SessionStart):
        print(f"{GREY}# Type '..' to undo previous input{RESET}")
        print(f"{GREY}# Press 'enter' to skip fields marked with {BLUE}?{RESET}")
        print(f"\n{_format_header(step_cur)}")
        return run_user_session(step_cur.next, parsers, _res)
    elif isinstance(step_cur, SessionEnd):
        print()
        prompt = _format_control_flow_prompt("Finish?")
        answer = _prompt_literal(prompt, accepted=["y", "n"], hidden=[".."])
        if answer == "y":
            return _res
        return _handle_undo(step_cur, parsers, _res)
    elif isinstance(step_cur, ContextStep):
        if skip_target := step_cur.skip_target:
            if annotation := step_cur.field.annotation:
                annotation_fmt = f"\n{_format_node_annotation(annotation)}"
            else:
                annotation_fmt = ""

            cur_fmt = _normalize_name(
                step_cur.name
            )  # Field name may be more specific than the class name
            parent_fmt = _get_contextual_name(step_cur.parent)
            if info := step_cur.position_info:
                repeats_fmt = f" ({info.total_repeats})"
            else:
                repeats_fmt = ""
            prompt = _format_control_flow_prompt(
                f"Add {cur_fmt}{repeats_fmt} to {parent_fmt}?"
            )

            print(annotation_fmt)
            answer = _prompt_literal(prompt, accepted=["y", "n"], hidden=[".."])
            if answer == "n":
                return run_user_session(skip_target, parsers, _res)
            elif answer == "..":
                return _handle_undo(step_cur, parsers, _res)

        return run_user_session(step_cur.next, parsers, _res)
    elif isinstance(step_cur, InputStep):
        if _res:
            prev_parent = _res[-1].input_step.parent
            if step_cur.parent != prev_parent:
                header = _format_header(step_cur.parent)
                print(f"\n{header}")
        elif not _res and not isinstance(
            step_cur.prev, SessionStart
        ):  # GraphStart prints its own header
            header = _format_header(step_cur.parent)
            print(f"\n{header}")

        # Only print annotation of parent when it hasn't been printed before
        if (
            isinstance(step_cur.prev, ContextStep)
            and step_cur.prev.field.annotation
            and not step_cur.prev.skip_target
        ):
            print(_format_node_annotation(step_cur.prev.field.annotation))

        prompt = _format_input_step(step_cur)
        v_input = input(prompt).strip()
        fld = step_cur.field

        # Special cases
        if v_input == "..":
            # Undo previous input
            return _handle_undo(step_cur, parsers, _res)
        elif v_input == "":
            # Skip optional or select default value
            if any(v is not MISSING for v in (fld.default, fld.default_factory)):
                v = fld.default if fld.default is not MISSING else fld.default_factory()
                _res.append(UserInput(v, step_cur))
            elif _can_skip(fld):
                _res.append(UserInput(None, step_cur))
            else:
                print(_format_input_error("must provide input"))
                return run_user_session(step_cur, parsers, _res)
        else:
            # Normal case
            try:
                v_parsed = parse_input(v_input, fld.shape, parsers)
            except AssertionError:
                raise
            except Exception as e:
                print(_format_input_error(e))
                return run_user_session(step_cur, parsers, _res)
            else:
                # Handle container-alias
                # TODO: Should I put base of fld.type on the NormalizedField obj?
                if isinstance(
                    fld.shape, (ContainerShape, DictShape, FixedContainerShape)
                ):
                    base_type, _ = get_type_base_args(fld.type)
                    v_parsed = base_type(v_parsed)

                _res.append(UserInput(v_parsed, step_cur))

        # TODO: Search for other repeat entries in the tree - will probably need to flag that user does NOT want to repeat certain nodes? Or is the tree structure sufficient
        if repeat_entry := step_cur.repeat_entry:
            parent_fmt = _get_contextual_name(repeat_entry.parent)
            grandparent_fmt = _get_contextual_name(repeat_entry.parent.parent)
            prompt = _format_control_flow_prompt(
                f"Add another {parent_fmt} to {grandparent_fmt}?"
            )

            print()
            answer = _prompt_literal(prompt, accepted=["y", "n"], hidden=[".."])
            if answer == "y":
                header = _format_header(repeat_entry.parent)
                print(f"\n{header}")
                return run_user_session(repeat_entry, parsers, _res)
            elif answer == "..":
                return _handle_undo(step_cur, parsers, _res)

        return run_user_session(step_cur.next, parsers, _res)


def _prompt_literal(
    prompt: str, accepted: list[str], hidden: list[str] | None = None
) -> str:
    hidden = hidden or []

    while True:
        prompt_fmt = f"{prompt} <{'/'.join(accepted)}> : "
        v = input(prompt_fmt).strip().lower()
        if v in accepted + hidden:
            return v
        accepted_fmt = " or ".join(f"'{v}'" for v in accepted)
        print(_format_input_error(f"value must be {accepted_fmt}"))


def _handle_undo(
    step_cur: SessionStep, parsers: ParserRegistry, res: list[UserInput]
) -> list[UserInput]:
    if not res:
        print(_format_input_error("no previous input to undo"))
        return run_user_session(step_cur, parsers, res)

    input_to_undo = res.pop()
    part_undo = input_to_undo.input_step
    if (
        isinstance(step_cur, (InputStep, ContextStep))
        and part_undo.parent != step_cur.parent
    ):
        print(f"\n{_format_header(part_undo.parent)}")

    return run_user_session(part_undo, parsers, res)


def _format_input_error(e: Exception | str) -> str:
    msg = str(e).strip()
    if msg.endswith("."):
        msg = msg[:-1]

    return f"{RED}> Invalid input: {msg}.{RESET}"


def _format_header(step: SessionStart | ContextStep) -> str:
    assert isinstance(step, (SessionStart, ContextStep))

    if isinstance(step, SessionStart):
        return f"[{BOLD}{_normalize_name(step.name)}{RESET}]"
    elif isinstance(step, ContextStep):
        location_cur = _get_contextual_name(step)
        location_prev = _get_contextual_name(step.parent)
        location_cur_fmt = (
            f"{BOLD}{location_cur}{RESET}{GREY} <- {location_prev}{RESET}"
        )

        repeat_n_fmt = ""
        if isinstance(step, ContextStep) and step.position_info:
            repeat_n_fmt = (
                f" {step.position_info.n_repeat} of {step.position_info.total_repeats}"
            )

        return f"[{location_cur_fmt}{repeat_n_fmt}]"


def _format_node_annotation(annotation: str) -> str:
    return f"{GREY}# {annotation}{RESET}"


def _format_input_step(part: InputStep) -> str:
    fld = part.field

    name_fmt = _normalize_name(part.name)
    if _can_skip(fld):
        name_fmt += f"{BLUE}?{RESET}"

    input_hint = []
    if t_fmt := _format_input_type_hint(fld.shape):
        input_hint.append(t_fmt)
    if annotation := fld.annotation:
        input_hint.append(annotation)
    input_hint_fmt = f" <{': '.join(input_hint)}>" if input_hint else ""

    v_def_fmt = (
        ""
        if fld.default in (MISSING, None)
        else f"{GREY}(default: {fld.default}){RESET} "
    )

    return f"{name_fmt}{input_hint_fmt} : {v_def_fmt}"


def _format_control_flow_prompt(prompt: str) -> str:
    return f"{GREEN}>{RESET} {prompt}"


def _format_input_type_hint(shape: TerminalShape) -> str:
    if isinstance(shape, ContainerShape):
        if isinstance(shape.element, (ContainerShape, FixedContainerShape)):
            return f"({_format_input_type_hint(shape.element)}), ..."
        elif shape.element.value_type in (Any, str):
            return "str, ..."
        else:
            return f"{_format_input_type_hint(shape.element)}, ..."
    elif isinstance(shape, DictShape):
        dict_args = [
            "str" if arg is Any else arg.__name__ for arg in (shape.key, shape.value)
        ]
        return f"({', '.join(dict_args)}), ..."
    elif isinstance(shape, FixedContainerShape):
        shape_fmt = []
        for el in shape.elements:
            if isinstance(el, (ContainerShape, FixedContainerShape)):
                shape_fmt.append(f"({_format_input_type_hint(el)})")
            elif el.value_type in (Any, str):
                shape_fmt.append("str")
            else:
                shape_fmt.append(_format_input_type_hint(el))
        return ", ".join(shape_fmt)
    elif isinstance(shape, AtomicShape):
        if shape.value_type in (Any, str):
            return ""
        elif shape.value_type is bool:
            return "y/n"
        else:
            return shape.value_type.__name__
    elif isinstance(shape, LiteralShape):
        return "/".join(str(v) for v in shape.values)


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


def _can_skip(fld: NormalizedField) -> bool:
    return (
        fld.is_optional
        or fld.default is None
        or fld.default_factory is not MISSING
        or isinstance(fld.shape, (ContainerShape, DictShape))
    )


def _get_contextual_name(step: SessionStart | InputStep | ContextStep) -> str:
    """
    Return the field name by default.

    If the current context crosses a container-entry boundary
    (skip_target), return the schema type name instead.
    """
    to_check = step if isinstance(step, (SessionStart, ContextStep)) else step.parent

    while True:
        # Default case
        if isinstance(to_check, SessionStart):
            return _normalize_name(step.name)
        # Crosses container-entry boundary
        elif to_check.skip_target:
            return _normalize_name(step.field.shape.schema_type.__name__)
        to_check = to_check.parent
