from __future__ import annotations

from dataclasses import replace
from typing import cast

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
    """
    Expand FixedSchemaContainerShape contexts (e.g. tuple[T, T]) into N repeated
    context traversals.

    Critical invariant: cloned InputSteps/ContextEntries must have their `.parent`
    pointing to the cloned parent, not the original one. Otherwise initialization
    cannot group inputs by context_path/iteration correctly.
    """
    res: list[SessionStart | ContextEntry | InputStep | SessionEnd] = []
    i = 0

    while i < len(steps):
        step_cur = steps[i]

        # Keep non-fixed-schema-container steps as-is
        if (
            isinstance(step_cur, (SessionStart, SessionEnd))
            or not isinstance(step_cur, ContextEntry)
            or not isinstance(step_cur.field.shape, FixedSchemaContainerShape)
        ):
            res.append(step_cur)
            i += 1
            continue

        # step_cur is the fixed schema container ContextEntry
        shape = cast(FixedSchemaContainerShape, step_cur.field.shape)

        # Collect its contiguous descendant subgraph (ContextEntry/InputStep only)
        remaining = steps[i + 1 :]
        subgraph: list[ContextEntry | InputStep] = [
            step
            for step in remaining
            if isinstance(step, (ContextEntry, InputStep))
            and is_child_path(step_cur.field.path, step.field.path)
        ]

        to_repeat: list[ContextEntry | InputStep] = [step_cur] + subgraph
        n_repeats = shape.length

        # Repeat N times: clone the whole subtree, remapping parent pointers
        for n in range(n_repeats):
            # We avoid hashing steps by using id(orig_step) -> clone_step
            clone_by_id: dict[int, ContextEntry | InputStep] = {}
            originals: list[ContextEntry | InputStep] = []
            clones: list[ContextEntry | InputStep] = []

            # 1) Clone nodes (parents rebound in pass 2)
            for step in to_repeat:
                if isinstance(step, InputStep):
                    clone: ContextEntry | InputStep = InputStep(field=step.field, parent=None)  # type: ignore[arg-type]
                else:
                    fld = step.field
                    # Tuple[T, T] | None is only optional for the first element
                    if step is step_cur and n > 0:
                        fld = replace(fld, is_optional=False)

                    clone = ContextEntry(field=fld, parent=None)  # type: ignore[arg-type]

                    if step is step_cur:
                        clone.position_info = PositionInfo(n + 1, n_repeats)

                originals.append(step)
                clones.append(clone)
                clone_by_id[id(step)] = clone

            # 2) Rebind parents (if parent is in subtree, point to cloned parent)
            for orig, clone in zip(originals, clones):
                orig_parent = orig.parent
                if orig_parent is None:
                    clone.parent = None
                elif id(orig_parent) in clone_by_id:
                    clone.parent = clone_by_id[id(orig_parent)]  # type: ignore[assignment]
                else:
                    clone.parent = orig_parent  # type: ignore[assignment]

            # 3) Append clones in preorder
            res.extend(cast(list[SessionStart | ContextEntry | InputStep | SessionEnd], clones))

        # Skip past the original subtree in the input list
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
        if isinstance(step_cur, SessionStart):
            res.append(step_cur)
            continue

        # RepeatExits come right before next non-child; outer contexts have priority over inner contexts
        if isinstance(step_cur, ContextEntry) and isinstance(
            step_cur.field.shape, SchemaContainerShape
        ):
            rxt = RepeatExit(parent=step_cur, element_start=steps[i + 1])
            remaining = steps[i + 1 :]
            next_non_child = _next_input_or_context_outside_cur(remaining, step_cur)
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
            skip_target_i = remaining.index(last_descendant) + 1
            skip_target = remaining[skip_target_i]
            assert isinstance(skip_target, (ContextEntry, InputStep, RepeatExit, SessionEnd))
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
    next_outside_cur = _next_input_or_context_outside_cur(remaining, context)
    i_to_check = remaining.index(next_outside_cur) - 1
    while True:
        step = remaining[i_to_check]
        assert isinstance(step, (ContextEntry, InputStep, RepeatExit))
        if is_child_path(context.field.path, step.field.path):
            assert isinstance(step, InputStep)
            return step
        i_to_check -= 1


def _next_input_or_context_outside_cur(
    remaining: list[SessionStep], context: ContextEntry
) -> InputStep | ContextEntry | SessionEnd:
    return next(
        step
        for step in remaining
        if isinstance(step, SessionEnd)
        or (
            isinstance(step, (InputStep, ContextEntry))
        and not context.field.path == step.field.path[:len(context.field.path)]
        )
    )
