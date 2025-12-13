from __future__ import annotations

ISSUES_LINK = "https://github.com/jdvanwijk/dc-input/issues"


class DcError(Exception):
    """Base class for library errors"""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class InputError(DcError):
    """Invalid user input errors"""

    def __init__(self, msg: Exception | str) -> None:
        super().__init__(msg)


class InternalError(DcError):
    """Critical library error"""

    def __init__(self, msg: Exception | str) -> None:
        msg_fmt = f"{msg} (Please file issue at {ISSUES_LINK} - thanks!)"
        super().__init__(msg_fmt)


class ParserRegistryError(DcError):
    """Invalid user Parser registry errors"""

    def __init__(self, msg: Exception | str):
        super().__init__(msg)


class SchemaError(DcError):
    """Invalid user Schema errors"""

    def __init__(self, msg: Exception | str) -> None:
        msg_fmt = (
            f"{msg} (If you received this error during data input, "
            f"please file issue at {ISSUES_LINK} - thanks!)"
        )
        super().__init__(msg_fmt)
