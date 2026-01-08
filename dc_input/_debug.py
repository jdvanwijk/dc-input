import logging

from ._types import NormalizedSchema, SessionStart, SessionEnd

logger = logging.getLogger("dc_input")


def log_normalized_schema(sc: NormalizedSchema) -> None:
    logger.debug("===== NORMALIZED SCHEMA =====")

    for path, fld in sc.items():
        logger.debug("%s : %s", path, fld)


def log_session_graph(start: SessionStart) -> None:
    logger.debug("===== SESSION GRAPH =====")

    cur = start
    while True:
        logger.debug("%r", cur)
        if isinstance(cur, SessionEnd):
            break
        cur = cur.next
