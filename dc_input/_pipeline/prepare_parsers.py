from __future__ import annotations

from dc_input._types import ParserRegistry


# ------------------------------------------------------------
# Default parsers for builtin primitives
# ------------------------------------------------------------
def _parse_bool(s: str) -> bool:
    s = s.strip().lower()
    yes = ("y", "yes", "1", "t", "true")
    no = ("n", "no", "0", "f", "false")
    if s not in yes + no:
        raise ValueError(f"must be 'y' or 'n'")
    return s in yes


def _parse_float(s: str) -> float:
    s = s.strip().replace(",", ".")
    try:
        return float(s)
    except (TypeError, ValueError):
        raise ValueError("'float' must be a number")


def _parse_int(s: str) -> int:
    s = s.strip()
    try:
        return int(s)
    except (TypeError, ValueError):
        raise ValueError("'int' must be a round number")


def _parse_str(s: str) -> str:
    return s.strip()


def _get_primitive_parsers() -> ParserRegistry:
    return {
        bool: _parse_bool,
        float: _parse_float,
        int: _parse_int,
        str: _parse_str,
    }


# ------------------------------------------------------------
# Main function
# ------------------------------------------------------------
def prepare_parsers(parsers_to_add: ParserRegistry) -> ParserRegistry:
    """
    Merge a registry of user provided parsers with the parsers provided by the library.
    Library parsers have priority.
    """
    return parsers_to_add | _get_primitive_parsers()
