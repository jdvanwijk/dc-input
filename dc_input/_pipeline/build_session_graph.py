from __future__ import annotations

from dataclasses import replace

from dc_input._types import (
    ContextEntry,
    InputStep,
    SessionEnd,
    SessionStart,
    SessionStep,
    NormalizedSchema,
    AtomicShape,
    LiteralShape,
    ContainerShape,
    FixedContainerShape,
    DictShape,
    FixedSchemaContainerShape,
    PositionInfo,
    KeyPath,
    SchemaContainerShape,
    RepeatExit,
)
from dc_input._pipeline._utils import is_child_path


# ------------------------------------------------------------
# Main functions
# ------------------------------------------------------------
def build_session_graph(sc: NormalizedSchema, base_name: str) -> SessionStart:
    res = _get_base_graph(sc, base_name)
    res = _expand_fixed_schema_containers(res)
    res = _add_repeat_exits(res)
    res = _add_skips(res)
    _link_graph(res)

    start = res[0]
    assert isinstance(start, SessionStart)

    return start


def _get_base_graph(
    sc: NormalizedSchema, base_name: str
) -> list[SessionStart | ContextEntry | InputStep | SessionEnd]:
    res_temp: dict[KeyPath, SessionStart | ContextEntry | InputStep | SessionEnd] = {
        (): SessionStart(name=base_name)
    }

    for fld in sc.values():
        parent_path = fld.path[:-1]
        parent = res_temp[parent_path]
        assert isinstance(parent, (SessionStart, ContextEntry))
        if isinstance(
            fld.shape,
            (
                AtomicShape,
                ContainerShape,
                DictShape,
                FixedContainerShape,
                LiteralShape,
            ),
        ):
            res_temp[fld.path] = InputStep(fld, parent=parent)
        else:
            res_temp[fld.path] = ContextEntry(fld, parent=parent)

    return list(res_temp.values()) + [SessionEnd()]


def _expand_fixed_schema_containers(
    steps: list[SessionStart | ContextEntry | InputStep | SessionEnd],
) -> list[SessionStart | ContextEntry | InputStep | SessionEnd]:
    res: list[SessionStart | ContextEntry | InputStep | SessionEnd] = []

    i = 0
    while i < len(steps):
        step_cur = steps[i]
        if isinstance(step_cur, (SessionStart, SessionEnd)) or (
            isinstance(step_cur, (ContextEntry, InputStep))
            and not isinstance(step_cur.field.shape, FixedSchemaContainerShape)
        ):
            res.append(step_cur)
            i += 1
            continue

        assert isinstance(step_cur, (ContextEntry, InputStep))
        assert isinstance(step_cur.field.shape, FixedSchemaContainerShape)

        remaining = steps[i + 1 :]
        subgraph = [
            step
            for step in remaining
            if isinstance(step, (ContextEntry, InputStep))
            and is_child_path(step_cur.field.path, step.field.path)
        ]
        to_repeat = [step_cur] + subgraph
        n_repeats = step_cur.field.shape.length

        for n in range(n_repeats):
            for step in to_repeat:
                if isinstance(step, InputStep):
                    step_clone = InputStep(field=step.field, parent=step.parent)
                else:
                    # Tuple[T, T] | None is only optional for the first T
                    if step is step_cur and n > 0:
                        field_replace = replace(step.field, is_optional=False)
                        step_clone = ContextEntry(field_replace, parent=step.parent)
                    else:
                        step_clone = ContextEntry(field=step.field, parent=step.parent)

                    if step is step_cur:
                        step_clone.position_info = PositionInfo(n + 1, n_repeats)

                res.append(step_clone)

        i += len(to_repeat)

    return res


def _add_repeat_exits(
    steps: list[SessionStart | ContextEntry | InputStep | SessionEnd],
) -> list[SessionStep]:
    res: list[SessionStep] = []
    pending: list[
        tuple[SessionStart | ContextEntry | InputStep | SessionEnd, RepeatExit]
    ] = []

    for i, step_cur in enumerate(steps):
        if isinstance(step_cur, (SessionStart, SessionEnd)):
            res.append(step_cur)
            continue

        # RepeatExits come right before next non-child; outer contexts have priority over inner contexts
        if isinstance(step_cur, ContextEntry) and isinstance(
            step_cur.field.shape, SchemaContainerShape
        ):
            rxt = RepeatExit(parent=step_cur, element_start=steps[i + 1])
            remaining = steps[i + 1 :]
            next_non_child = _find_next_non_child(remaining, step_cur)
            pending.insert(0, (next_non_child, rxt))

        for pair in pending[:]:
            step, rxt = pair
            if step is step_cur:
                res.append(rxt)
                pending.remove(pair)

        res.append(step_cur)

    return res


def _add_skips(steps: list[SessionStep]) -> list[SessionStep]:
    res: list[SessionStep] = []

    for i, step_cur in enumerate(steps):
        if not isinstance(step_cur, ContextEntry):
            res.append(step_cur)
            continue

        remaining = steps[i + 1 :]
        shape = step_cur.field.shape
        if isinstance(shape, SchemaContainerShape):
            # Skip target is step directly after matching RepeatExit
            for i_remaining, step in enumerate(remaining):
                if isinstance(step, RepeatExit) and step.parent is step_cur:
                    skip_target = remaining[i_remaining + 1]
                    assert isinstance(
                        skip_target, (ContextEntry, InputStep, SessionEnd, RepeatExit)
                    )
                    step_cur.skip_target = skip_target
                    break
        elif step_cur.field.is_optional:
            # Skip target is step directly after last descendant of context
            last_descendant = _find_last_descendant(remaining, step_cur)
            skip_target = remaining.index(last_descendant) + 1
            step_cur.skip_target = skip_target

        res.append(step_cur)

    return res


def _link_graph(steps: list[SessionStep]) -> None:
    for prev, cur in zip(steps, steps[1:]):
        prev.next = cur
        cur.prev = prev


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _find_last_descendant(
    remaining: list[SessionStep], context: ContextEntry
) -> InputStep:
    next_non_child = _find_next_non_child(remaining, context)
    i_to_check = remaining.index(next_non_child) - 1
    while True:
        step = remaining[i_to_check]
        assert isinstance(step, (ContextEntry, InputStep, RepeatExit))
        if is_child_path(context.field.path, step.field.path):
            assert isinstance(step, InputStep)
            return step
        i_to_check -= 1


def _find_next_non_child(
    remaining: list[SessionStep], context: ContextEntry
) -> InputStep | ContextEntry | SessionEnd:
    return next(
        step
        for step in remaining
        if isinstance(step, SessionEnd)
        or (
            isinstance(step, (InputStep, ContextEntry))
            and not is_child_path(context.field.path, step.field.path)
        )
    )
