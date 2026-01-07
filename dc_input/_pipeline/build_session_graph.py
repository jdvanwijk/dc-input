from __future__ import annotations

from dataclasses import replace

from dc_input._types import (
    ContextStep,
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
    SchemaShape,
    SchemaContainerShape,
)
from dc_input._utils import is_child_path


def build_session_graph(sc: NormalizedSchema, base_name: str) -> SessionStart:
    res = _get_base_graph(sc, base_name)
    res = _expand_fixed_schema_containers(res)
    res = _add_skip_repeat_edges(res)
    _link_graph(res)

    start = res[0]
    assert isinstance(start, SessionStart)

    return start


def _get_base_graph(sc: NormalizedSchema, base_name: str) -> list[SessionStep]:
    res_temp: dict[KeyPath, SessionStep] = {(): SessionStart(name=base_name)}

    for fld in sc.values():
        parent_path = fld.path[:-1]
        parent = res_temp[parent_path]
        assert isinstance(parent, (SessionStart, ContextStep))
        if isinstance(
            fld.shape,
            (
                ContainerShape,
                DictShape,
                FixedContainerShape,
                AtomicShape,
                LiteralShape,
            ),
        ):
            res_temp[fld.path] = InputStep(fld, parent=parent)
        else:
            res_temp[fld.path] = ContextStep(fld, parent=parent)

    return list(res_temp.values()) + [SessionEnd()]


def _expand_fixed_schema_containers(
    steps: list[SessionStep],
) -> list[SessionStep]:
    res: list[SessionStep] = []

    i = 0
    while i < len(steps):
        step_cur = steps[i]
        if isinstance(step_cur, (SessionStart, SessionEnd)) or (
            isinstance(step_cur, (ContextStep, InputStep))
            and not isinstance(step_cur.field.shape, FixedSchemaContainerShape)
        ):
            res.append(step_cur)
            i += 1
            continue

        assert isinstance(step_cur.field.shape, FixedSchemaContainerShape)

        remaining = steps[i + 1 :]
        subgraph = [
            step
            for step in remaining
            if isinstance(step, (ContextStep, InputStep))
               and is_child_path(step_cur.field.path, step.field.path)
        ]
        to_repeat = [step_cur] + subgraph
        n_repeats = step_cur.field.shape.length

        for n in range(n_repeats):
            for step in to_repeat:
                if isinstance(step, InputStep):
                    part_clone = InputStep(field=step.field, parent=step.parent)
                else:
                    # Tuple[T, T] | None is only optional for the first T
                    if step is step_cur and n > 0:
                        field_replace = replace(step.field, is_optional=False)
                        part_clone = ContextStep(field_replace, parent=step.parent)
                    else:
                        part_clone = ContextStep(field=step.field, parent=step.parent)

                    if step is step_cur:
                        part_clone.position_info = PositionInfo(n + 1, n_repeats)

                res.append(part_clone)

        i += len(to_repeat)

    return res


def _add_skip_repeat_edges(steps: list[SessionStep]) -> list[SessionStep]:
    res: list[SessionStep] = []

    for i, step_cur in enumerate(steps):
        if not isinstance(step_cur, ContextStep):
            res.append(step_cur)
            continue

        remaining = steps[i + 1 :]
        shape = step_cur.field.shape
        if isinstance(shape, (SchemaShape, FixedContainerShape)):
            if not step_cur.field.is_optional:
                res.append(step_cur)
                continue

            skip_target = _find_next_non_child(remaining, step_cur)
            step_cur.skip_target = skip_target
            res.append(step_cur)
        elif isinstance(shape, SchemaContainerShape):
            skip_target = _find_next_non_child(remaining, step_cur)
            step_cur.skip_target = skip_target

            repeat_entry = steps[i + 1]
            assert isinstance(repeat_entry, (InputStep, ContextStep))
            i_repeat_from = steps.index(skip_target) - 1
            repeat_from = steps[i_repeat_from]
            assert isinstance(repeat_from, InputStep)
            repeat_from.repeat_entry = repeat_entry

            res.append(step_cur)

    return res


def _link_graph(steps: list[SessionStep]) -> None:
    for prev, cur in zip(steps, steps[1:]):
        prev.next = cur
        cur.prev = prev


def _find_next_non_child(
    remaining: list[SessionStep], context: ContextStep
) -> InputStep | ContextStep | SessionEnd:
    return next(
        step
        for step in remaining
        if isinstance(step, SessionEnd)
        or (
            isinstance(step, (InputStep, ContextStep))
            and not is_child_path(context.field.path, step.field.path)
        )
    )
