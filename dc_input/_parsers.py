from __future__ import annotations

from types import NoneType

from dc_input._types import ParserRegistry


# ------------------------------------------------------------
# Default parsers for builtin primitives (and None)
# ------------------------------------------------------------
def _parse_str(s: str) -> str:
    return s


def _parse_int(s: str) -> int:
    return int(s)


def _parse_float(s: str) -> float:
    return float(s)


def _parse_bool(s: str) -> bool:
    sl = s.strip().lower()
    true = ("1", "true", "t", "yes", "y")
    false = ("0", "false", "f", "no", "n")
    if sl in true:
        return True
    if sl in false:
        return False
    raise ValueError(f"value must be in {true} for True or {false} for False")


def _parse_none(s: str) -> None:
    sl = s.strip().lower()
    none = ("", "none", "null")
    if sl in none:
        return None
    raise ValueError(f"value must be in {none}")


# ------------------------------------------------------------
# Main function
# ------------------------------------------------------------
def get_default_registry() -> ParserRegistry:
    return {
        str: _parse_str,
        int: _parse_int,
        float: _parse_float,
        bool: _parse_bool,
        NoneType: _parse_none,
    }
