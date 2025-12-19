from __future__ import annotations

from types import NoneType, UnionType
from typing import Annotated, Any, Literal, Union

from dc_input._types import ParserFunc, ParserRegistry

from dc_input._utils import get_type_base_args, safe_issubclass, get_optional_non_none


# ------------------------------------------------------------
# Main parsing functions
# ------------------------------------------------------------
def parse_input(value: str, t: Any, registry: ParserRegistry):
    """
    Entry point of the pipeline.

    - Optional[T] => parse flat/nested based on T
    - Containers (list, set, tuple, dict and subclasses) => nested parsing
    - All other types => flat parsing
    """
    base, args = get_type_base_args(t)

    # ---------- Handle Union[T, None] ----------
    if base is UnionType or base is Union:
        # assume parse_schema rejects all other unions
        elem_t = get_optional_non_none(t)
        elem_t_base, _ = get_type_base_args(elem_t)

        # Choose flat or nested based on inner T
        if _is_container_type(elem_t_base):
            structure = _parse_structure_nested(value)
        else:
            structure = _parse_structure_flat(value)

        return _coerce(structure, t, registry)

    # ---------- Handle all other types ----------
    if _is_container_type(base):
        structure = _parse_structure_nested(value)
    else:
        structure = _parse_structure_flat(value)

    return _coerce(structure, t, registry)


def _coerce(value: str | list, t: Any, registry: ParserRegistry):
    assert isinstance(value, (str, list))

    base, args = get_type_base_args(t)

    # ---------- Annotated, Any, Literal ----------
    if base is Annotated:
        return _coerce(value, args[0], registry)

    if base is Any:
        return value

    if base is Literal:
        for arg in args:
            if str(arg) == value:
                return arg
        raise ValueError(f"value must be in {args}")

    # ---------- Union[T, None] ----------
    if base is UnionType or base is Union:
        # Assume parse_schema ensures this is Optional[T]
        elem_t = args[0] if args[0] is not NoneType else args[1]
        try:
            # try None parser first - value might be provided as ["none"] when T is a container
            possible_none = value[0] if isinstance(value, list) else value
            parser = registry[NoneType]
            return parser(possible_none)
        except Exception:
            # parse T if None parser fails
            return _coerce(value, elem_t, registry)

    # ---------- List, set (+ subclasses) ----------
    if safe_issubclass(base, (list, set)):
        if not isinstance(value, list):
            raise ValueError(
                "Input does not match type structure (missing parenthesis?)"
            )

        elem_t = args[0] if args else Any
        coerced = [_coerce(v, elem_t, registry) for v in value]
        return base(coerced)

    # ---------- Tuple (+ subclasses) ----------
    if safe_issubclass(base, tuple):
        if not isinstance(value, list):
            raise ValueError(
                "Input does not match type structure (missing parenthesis?)"
            )

        if not args:
            coerced = [_coerce(v, Any, registry) for v in value]
            return base(coerced)
        elif len(args) == 2 and args[1] is Ellipsis:  # tuple[T, ...]
            elem_t = args[0]
            coerced = [_coerce(v, elem_t, registry) for v in value]
            return base(coerced)
        else:
            if len(value) != len(args):
                raise ValueError(
                    "number of values does not match number of tuple parameters"
                )
            coerced = [_coerce(v, elem_t, registry) for v, elem_t in zip(value, args)]
            return base(coerced)

    # ---------- Dict (+ subclasses) ----------
    if safe_issubclass(base, dict):
        if not isinstance(value, list):
            raise ValueError("dict entries must be comma-separated (k,v) pairs")

        key_t, val_t = args if args else (Any, Any)
        result = base()
        for pair in value:
            if len(pair) != 2:
                raise ValueError(
                    f"dict entries must be comma-separated (k,v) pairs; got {pair!r}"
                )

            k_raw, v_raw = pair
            k = _coerce(k_raw, key_t, registry)
            v = _coerce(v_raw, val_t, registry)
            result[k] = v

        return result

    # ---------- All other types ----------
    # Assume simple type
    parser = _select_parser(base, registry)
    return parser(value)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _is_container_type(base: Any) -> bool:
    return safe_issubclass(base, (dict, list, set, tuple))


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
    Locate a parser for `base`:
      1. registry.parsers exact lookup
      2. MRO fallback if base is a class
      3. Call base directly
    """
    if parser := registry.get(base):
        return parser

    if isinstance(base, type):
        for cls in base.__mro__[1:]:
            if parser := registry.get(cls):
                return parser

    if isinstance(base, type):
        return lambda s: base(s)

    # User did not provide valid parser for base
    raise ValueError(f"No parser available for type {base!r}")
