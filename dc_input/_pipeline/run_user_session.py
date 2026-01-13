from dataclasses import MISSING
from typing import Any

from dc_input._pipeline._parse_input import parse_input
from dc_input._types import (
    SessionStart,
    ParserRegistry,
    UserInput,
    SessionStep,
    SessionEnd,
    ContextEntry,
    InputStep,
    ContainerShape,
    DictShape,
    AtomicShape,
    FixedContainerShape,
    NormalizedField,
    InputShape,
    SchemaContainerShape,
    SessionResult,
    RepeatExit,
)


BLUE = "\033[36m"
GREEN = "\033[32m"
GREY = "\033[90m"
RED = "\033[31m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ------------------------------------------------------------
# Main control flow functions
# ------------------------------------------------------------
def run_user_session(
    step_cur: SessionStep,
    parsers: ParserRegistry,
    _res: SessionResult | None = None,
) -> SessionResult:
    if _res is None:
        _res = []

    handlers = {
        SessionStart: _handle_session_start,
        ContextEntry: _handle_context_entry_step,
        InputStep: _handle_input_step,
        RepeatExit: _handle_repeat_exit,
        SessionEnd: _handle_session_end,
    }

    assert isinstance(
        step_cur,
        (SessionStart, SessionEnd, ContextEntry, RepeatExit, InputStep),
    )

    handler = handlers[type(step_cur)]
    return handler(step_cur, parsers, _res)


def _handle_session_start(
    step_cur: SessionStart,
    parsers: ParserRegistry,
    res: SessionResult,
) -> SessionResult:
    print(f"{GREY}# Type '..' to undo previous input{RESET}")
    print(f"{GREY}# Press 'enter' to skip fields marked with {BLUE}?{RESET}")
    print(f"\n{_format_header(step_cur)}")
    return run_user_session(step_cur.next, parsers, res)


def _handle_context_entry_step(
    step_cur: ContextEntry,
    parsers: ParserRegistry,
    res: SessionResult,
) -> SessionResult:
    skip_target = step_cur.skip_target

    if not skip_target:
        print(f"\n{_format_header(step_cur)}")
        if step_cur.field.annotation:
            print(_format_node_annotation(step_cur.field.annotation))
        return run_user_session(step_cur.next, parsers, res)

    # Handle optional schema
    if annotation := step_cur.field.annotation:
        annotation_fmt = f"\n{_format_node_annotation(annotation)}"
    else:
        annotation_fmt = ""

    cur_fmt = _normalize_name(step_cur.name)
    parent_fmt = _normalize_name(_get_schema_name(step_cur.parent))

    if info := step_cur.position_info:
        repeats_fmt = f" ({info.total_repeats})"
    else:
        repeats_fmt = ""

    prompt = _format_control_flow_prompt(f"Add {cur_fmt}{repeats_fmt} to {parent_fmt}?")

    print(annotation_fmt)
    answer = _prompt_literal(prompt, accepted=["y", "n"], hidden=[".."])

    if answer == "y":
        print()
        print(_format_header(step_cur.next))
        return run_user_session(step_cur.next, parsers, res)
    elif answer == "n":
        return run_user_session(skip_target, parsers, res)
    else:
        return _handle_undo(step_cur, parsers, res)


def _handle_input_step(
    step_cur: InputStep,
    parsers: ParserRegistry,
    res: SessionResult,
) -> SessionResult:
    # Re-print context header if we re-entered a parent context
    if res:
        input_prev_context = res[-1].input_step.parent
        cur_context = step_cur.parent
        to_check = input_prev_context.parent

        while True:
            if cur_context == to_check:
                print()
                print(_format_header(step_cur.parent, continued=True))
                break
            elif to_check is None:
                break
            to_check = to_check.parent

    prompt = _format_input_step(step_cur)
    v_input = input(prompt).strip()
    fld = step_cur.field

    # Special cases
    if v_input == "..":
        return _handle_undo(step_cur, parsers, res)

    elif v_input == "":
        if any(v is not MISSING for v in (fld.default, fld.default_factory)):
            v = fld.default if fld.default is not MISSING else fld.default_factory()
            res.append(UserInput(v, step_cur))
        elif _can_skip(fld):
            res.append(UserInput(None, step_cur))
        else:
            print(_format_input_error("must provide input"))
            return run_user_session(step_cur, parsers, res)

    else:
        try:
            v_parsed = parse_input(v_input, fld.shape, parsers)
        except AssertionError:
            raise
        except Exception as e:
            print(_format_input_error(e))
            return run_user_session(step_cur, parsers, res)
        else:
            # Handle container-alias
            if isinstance(
                fld.shape,
                (ContainerShape, DictShape, FixedContainerShape),
            ):
                v_parsed = fld.type_non_aliased_base(v_parsed)

            res.append(UserInput(v_parsed, step_cur))

    return run_user_session(step_cur.next, parsers, res)


def _handle_repeat_exit(
    step_cur: RepeatExit,
    parsers: ParserRegistry,
    res: SessionResult,
) -> SessionResult:
    repeat_entry_fmt = _normalize_name(_get_schema_name(step_cur.parent))
    repeat_entry_parent_fmt = _normalize_name(step_cur.element_start.parent.name)

    prompt = _format_control_flow_prompt(
        f"Add another {repeat_entry_fmt} to {repeat_entry_parent_fmt}?"
    )

    print()
    answer = _prompt_literal(prompt, accepted=["y", "n"], hidden=[".."])

    if answer == "y":
        return run_user_session(step_cur.element_start, parsers, res)
    elif answer == "n":
        return run_user_session(step_cur.next, parsers, res)
    else:
        return _handle_undo(step_cur, parsers, res)


def _handle_session_end(
    step_cur: SessionEnd,
    parsers: ParserRegistry,
    res: SessionResult,
) -> SessionResult:
    print()
    prompt = _format_control_flow_prompt("Finish?")
    answer = _prompt_literal(prompt, accepted=["y", "n"], hidden=[".."])

    if answer == "y":
        return res

    return _handle_undo(step_cur, parsers, res)


# ------------------------------------------------------------
# Control flow helpers
# ------------------------------------------------------------
def _handle_undo(
    step_cur: SessionStep,
    parsers: ParserRegistry,
    res: SessionResult,
) -> SessionResult:
    if not res:
        print(_format_input_error("no previous input to undo"))
        return run_user_session(step_cur, parsers, res)

    input_to_undo = res.pop()
    step_undo = input_to_undo.input_step
    # If isinstance(step_undo.next, RepeatExit), we cross a repeat boundary of a SchemaContainer
    if isinstance(step_cur, SessionEnd) or step_undo.parent != step_cur.parent or isinstance(step_undo.next, RepeatExit):
        to_format = (
            step_cur.element_start
            if isinstance(step_cur, RepeatExit)
            else step_undo.parent
        )
        print()
        print(_format_header(to_format))
        # TODO [LOW]: A bit of an edge case, but this interacts with _handle_input_step when
        #  we undo into a continued context: the header gets printed twice

    # Prefix next input step prompt with ".."
    print(f"{GREY}..{RESET}", end="")

    return run_user_session(step_undo, parsers, res)


def _prompt_literal(
    prompt: str,
    accepted: list[str],
    hidden: list[str] | None = None,
) -> str:
    hidden = hidden or []

    while True:
        prompt_fmt = f"{prompt} <{'/'.join(accepted)}> : "
        v = input(prompt_fmt).strip().lower()

        if v in accepted + hidden:
            return v

        accepted_fmt = " or ".join(f"'{v}'" for v in accepted)
        print(_format_input_error(f"value must be {accepted_fmt}"))


# ------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------
def _format_input_error(e: Exception | str) -> str:
    msg = str(e).strip()
    if msg.endswith("."):
        msg = msg[:-1]
    return f"{RED}> Invalid input: {msg}.{RESET}"


def _format_header(
    step: SessionStart | InputStep | ContextEntry, continued: bool = False
) -> str:
    continued_fmt = " (contd.)" if continued else ""

    if isinstance(step, SessionStart):
        return f"[{BOLD}{_normalize_name(step.name)}{RESET}{continued_fmt}]"

    if isinstance(step.parent, ContextEntry) and isinstance(
        step.parent.field.shape, SchemaContainerShape
    ):
        location_cur = _normalize_name(_get_schema_name(step.parent))
        location_prev = _normalize_name(step.parent.name)
    else:
        location_cur = _normalize_name(step.name)
        location_prev = _normalize_name(step.parent.name)
    location_cur_fmt = (
        f"{BOLD}{location_cur}{continued_fmt}{RESET}{GREY} <- {location_prev}{RESET}"
    )

    repeat_n_fmt = ""
    if isinstance(step, ContextEntry) and step.position_info:
        repeat_n_fmt = (
            f" {step.position_info.n_repeat} of {step.position_info.total_repeats}"
        )

    return f"[{location_cur_fmt}{repeat_n_fmt}]"


def _format_node_annotation(annotation: str) -> str:
    return f"{GREY}# {annotation}{RESET}"


def _format_input_step(step: InputStep) -> str:
    fld = step.field
    name_fmt = _normalize_name(step.name)

    if _can_skip(fld):
        name_fmt += f"{BLUE}?{RESET}"

    input_hint = []
    if t_fmt := _format_input_type_hint(fld.shape):
        input_hint.append(t_fmt)
    if annotation := fld.annotation:
        input_hint.append(annotation)

    input_hint_fmt = f" <{': '.join(input_hint)}>" if input_hint else ""

    v_def_fmt = ""
    if (fld.default and fld.default is not MISSING) or fld.default in (False, 0):
        if fld.default is True:
            default = "y"
        elif fld.default is False:
            default = "n"
        else:
            default = fld.default
        v_def_fmt = f"{GREY}(default: {default}){RESET} "


    return f"{name_fmt}{input_hint_fmt} : {v_def_fmt}"


def _format_control_flow_prompt(prompt: str) -> str:
    return f"{GREEN}>{RESET} {prompt}"


def _format_input_type_hint(shape: InputShape) -> str:
    if isinstance(shape, AtomicShape):
        if shape.value_type in (Any, str):
            return ""
        elif shape.value_type is bool:
            return "y/n"
        else:
            return shape.value_type.__name__

    elif isinstance(shape, ContainerShape):
        if isinstance(shape.element, (ContainerShape, FixedContainerShape)):
            return f"({_format_input_type_hint(shape.element)}), ..."
        elif shape.element.value_type in (Any, str):
            return "str, ..."
        else:
            return f"{_format_input_type_hint(shape.element)}, ..."

    elif isinstance(shape, DictShape):
        dict_args = [
            "str" if arg is Any else arg.value_type.__name__ for arg in (shape.key, shape.value)
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

    else:  # LiteralShape
        return "/".join(str(v) for v in shape.values)


def _normalize_name(name: str) -> str:
    res: list[str] = []

    for i, ch in enumerate(name):
        if ch.isupper():
            if i == 0:
                res.append(ch.lower())
            else:
                res.append(f" {ch.lower()}")
        elif ch == "_":
            res.append(" ")
        else:
            res.append(ch)

    return "".join(res)


# ------------------------------------------------------------
# Other helpers
# ------------------------------------------------------------
def _can_skip(fld: NormalizedField) -> bool:
    return (
        fld.is_optional
        or fld.default is not MISSING
        or fld.default_factory is not MISSING
        or isinstance(fld.shape, (ContainerShape, DictShape))
    )


def _get_schema_name(step: SessionStep) -> str:
    if isinstance(step, SessionStart):
        return step.name
    return step.field.shape.schema_type.__name__
