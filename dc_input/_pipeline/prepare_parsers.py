from __future__ import annotations

from dc_input._types import ParserRegistry


# ------------------------------------------------------------
# Default parsers for builtin primitives
# ------------------------------------------------------------
def _parse_bool(s: str) -> bool:
    sl = s.strip().lower()
    if sl not in ("y", "n"):
        raise ValueError("must be 'y' or 'n'")
    return sl == "y"


def _parse_float(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        raise ValueError("must be a number")


def _parse_int(s: str) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        raise ValueError("must be a round number")


def _parse_str(s: str) -> str:
    return s


def _get_default_registry() -> ParserRegistry:
    return {
        bool: _parse_bool,
        float: _parse_float,
        int: _parse_int,
        str: _parse_str,
    }


# ------------------------------------------------------------
# Main function
# ------------------------------------------------------------
def prepare_parsers(custom: ParserRegistry) -> ParserRegistry:
    return _get_default_registry() | custom
