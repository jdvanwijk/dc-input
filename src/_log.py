from dataclasses import fields, is_dataclass, asdict
import logging
from typing import Any, get_type_hints

from dc_input._types import NormalizedSchema, SessionStart, KeyPath, SessionResult
from dc_input._version import VERSION

logger = logging.getLogger("dc_input")


def initialized_schema(sc: Any) -> None:
    logger.debug("===== INITIALIZED SCHEMA =====")

    sc_dict = asdict(sc)
    for k, v in sc_dict.items():
        logger.debug("%s : %r", k, v)


def normalized_schema(sc: NormalizedSchema) -> None:
    logger.debug("===== NORMALIZED SCHEMA =====")

    for path, fld in sc.items():
        logger.debug("%s : %s", path, fld)


def schema(sc: Any) -> None:
    logger.debug("===== SCHEMA =====")

    def _log(sc: Any, _path: KeyPath = ()) -> None:
        type_hints = get_type_hints(sc)

        for f in fields(sc):
            path_new = _path + (f.name,)
            logger.debug("%s : %r", path_new, f)

            t = type_hints[f.name]
            if is_dataclass(t):
                _log(t, path_new)

    _log(sc)


def session_graph(start: SessionStart) -> None:
    logger.debug("===== SESSION GRAPH =====")

    cur = start
    while True:
        logger.debug("%r", cur)
        if cur.next is None:
            break
        cur = cur.next


def session_result(res: SessionResult) -> None:
    logger.debug("===== SESSION RESULT =====")
    for inpt in res:
        logger.debug("%r", inpt)


def version() -> None:
    logger.debug("VERSION: %s", VERSION)