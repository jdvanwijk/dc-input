from __future__ import annotations

from typing import Any

from dc_input._types import (
    ParserFunc,
    ParserRegistry,
    FixedContainerShape,
    DictShape,
    ContainerShape,
    AtomicShape,
    LiteralShape,
)

from dc_input._pipeline._utils import alt_issubclass


# ------------------------------------------------------------
# Main parsing functions
# ------------------------------------------------------------
def parse_input(
    value: str,
    shape: ContainerShape | DictShape | FixedContainerShape | AtomicShape | LiteralShape,
    registry: ParserRegistry,
):
    """
    Entry point of the pipeline.

    - ContainerShape, DictShape, FixedContainerShape => nested parsing
    - LeafShape, LiteralShape => flat parsing
    """
    if isinstance(shape, (ContainerShape, DictShape, FixedContainerShape)):
        structure = _parse_structure_nested(value)
    else:
        structure = _parse_structure_flat(value)

    return _coerce(structure, shape, registry)


def _coerce(
    value: str | list,
    shape: ContainerShape | DictShape | FixedContainerShape | AtomicShape | LiteralShape,
    registry: ParserRegistry,
):
    if isinstance(shape, ContainerShape):
        return shape.container_type(_coerce(v, shape.element, registry) for v in value)
    elif isinstance(shape, DictShape):
        res = {}
        for pair in value:
            if len(pair) != 2:
                raise ValueError(f"comma-separated pairs required; got {pair!r}")
            k_raw, v_raw = pair
            k = _coerce(k_raw, shape.key, registry)
            v = _coerce(v_raw, shape.value, registry)
            res[k] = v

        return res
    elif isinstance(shape, FixedContainerShape):
        if len(value) != len(shape.elements):
            raise ValueError(
                f"invalid number of values (required: {len(shape.elements)})"
            )
        return shape.container_type(
            _coerce(v, el, registry) for v, el in zip(value, shape.elements)
        )
    elif isinstance(shape, AtomicShape):
        if isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], str):
                raise ValueError(f"unnecessary parentheses around {value[0]!r}")
            raise ValueError("unexpected grouping")

        if shape.value_type is Any:
            return value
        else:
            parser = _select_parser(shape.value_type, registry)
            return parser(value)
    elif isinstance(shape, LiteralShape):
        for v in shape.values:
            if str(v) == value:
                return v
        raise ValueError(f"value must be in {shape.values}")


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _is_container_type(base: Any) -> bool:
    return alt_issubclass(base, (dict, list, set, tuple))


def _parse_structure_flat(s: str) -> str:
    """Trim, unescape escapes, and return a flat token string."""
    s = s.strip()

    i = 0
    res = []
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            res.append(s[i + 1])
            i += 2
            continue
        res.append(ch)
        i += 1
    return "".join(res).strip()


def _parse_structure_nested(s: str) -> list[str | list]:
    """
    Parse comma-separated items with nested parentheses. Return lists of strings.
    Example:
      "a,b,(c,d),e" -> ["a","b",["c","d"],"e"]
      "(k,v),(k2,(a,b))" -> [ ["k","v"], ["k2", ["a","b"]] ]
    """
    s = s.strip()

    escape = False
    res: list = []
    stack: list[list] = [res]
    token: list[str] = []

    for ch in s:
        if escape:
            token.append(ch)
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == "(":
            cur = "".join(token).strip()
            if cur:
                stack[-1].append(cur)
            token = []
            new_list: list = []
            stack[-1].append(new_list)
            stack.append(new_list)
            continue
        if ch == ")":
            cur = "".join(token).strip()
            if cur:
                stack[-1].append(cur)
            token = []
            if len(stack) == 1:
                raise ValueError("Unmatched ')'")
            stack.pop()
            continue
        if ch == ",":
            cur = "".join(token).strip()
            if cur:
                stack[-1].append(cur)
            token = []
            continue
        token.append(ch)

    last = "".join(token).strip()
    if last:
        stack[-1].append(last)
    if len(stack) != 1:
        raise ValueError("Missing closing ')'")
    return res


def _select_parser(base: Any, registry: ParserRegistry) -> ParserFunc:
    """
    Locate a parser for `base` in the provided registry. If no parser is found, call base directly.
    """
    if parser := registry.get(base):
        return parser
    return lambda s: base(s)
