from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import is_dataclass
from typing import Any, TypeVar

from dc_input._types import (
    ContainerShape,
    ContextEntry,
    FixedContainerShape,
    FixedSchemaContainerShape,
    InputStep,
    KeyPath,
    NormalizedField,
    RepeatExit,
    SchemaContainerShape,
    SchemaShape,
    SessionStart,
    SessionStep,
    UserInput,
)
from dc_input._pipeline._utils import is_child_path

T = TypeVar("T")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def initialize_schema(schema: type[T], inputs: list[UserInput]) -> T:
    assert inputs
    assert is_dataclass(schema)

    # Find SessionStart (walk up parents from first InputStep)
    cur: Any = inputs[0].input_step
    while cur.parent is not None:
        cur = cur.parent
    start = cur
    assert isinstance(start, SessionStart)

    context_inputs = _collect_context_inputs(inputs)

    # Root behaves like a context with path ()
    children = list(_iter_root_children(start))

    return _build_context_instance(
        schema_type=schema,
        context_path=(),
        children=children,
        context_inputs=context_inputs,
        iteration=0,
    )


def _build_context_instance(
    *,
    schema_type: type,
    context_path: KeyPath,
    children: list[SessionStep],
    context_inputs: dict[KeyPath, dict[int, dict[str, Any]]],
    iteration: int,
) -> Any:
    values: dict[str, Any] = {}
    inputs_for_ctx = context_inputs.get(context_path, {}).get(iteration, {})

    for child in children:
        fld = child.field
        name = child.name

        # ── Nested schema (single instance) ─────────────────────
        if isinstance(child, ContextEntry) and isinstance(fld.shape, SchemaShape):
            values[name] = _build_context(child, context_inputs)

        # ── Schema containers (repeatable or fixed) ─────────────
        elif isinstance(child, ContextEntry) and isinstance(
            fld.shape, (SchemaContainerShape, FixedSchemaContainerShape)
        ):
            items = _build_repeated_context(child, context_inputs)

            # Use the internal container type first
            res = fld.shape.container_type(items)

            # Wrap back into unaliased container type when needed
            if fld.type_non_aliased_base != fld.shape.container_type:
                res = fld.type_non_aliased_base(res)

            values[name] = res

        # ── Terminal input ──────────────────────────────────────
        elif isinstance(child, InputStep):
            # If field was optional and skipped, it may be absent from inputs_for_ctx
            if name not in inputs_for_ctx:
                if fld.is_optional:
                    values[name] = None
                    continue
                raise KeyError(
                    f"Missing required input '{name}' for context {context_path} iteration {iteration}"
                )

            inpt = inputs_for_ctx[name]

            if isinstance(fld.shape, (FixedContainerShape, FixedSchemaContainerShape)):
                values[name] = _wrap_unaliased(fld, inpt)
            else:
                values[name] = inpt

        else:
            raise RuntimeError(
                f"Unhandled session step during initialization: {child!r}"
            )

    return schema_type(**values)


def _build_context(
    context: ContextEntry,
    context_inputs: dict[KeyPath, dict[int, dict[str, Any]]],
) -> Any:
    schema_type = context.field.shape.schema_type
    context_path = context.field.path

    iterations = context_inputs.get(context_path, {0: {}})
    children = list(_iter_context_children(context))

    instances = [
        _build_context_instance(
            schema_type=schema_type,
            context_path=context_path,
            children=children,
            context_inputs=context_inputs,
            iteration=i,
        )
        for i in sorted(iterations)
    ]

    return instances if len(instances) > 1 else instances[0]


def _build_repeated_context(
    context: ContextEntry,
    context_inputs: dict[KeyPath, dict[int, dict[str, Any]]],
) -> list[Any]:
    context_path = context.field.path
    iterations = context_inputs.get(context_path, {})

    children = list(_iter_context_children(context))
    schema_type = context.field.shape.schema_type

    return [
        _build_context_instance(
            schema_type=schema_type,
            context_path=context_path,
            children=children,
            context_inputs=context_inputs,
            iteration=i,
        )
        for i in sorted(iterations)
    ]


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _collect_context_inputs(
    inputs: list[UserInput],
) -> dict[KeyPath, dict[int, dict[str, Any]]]:
    """
    Maps:
        context_path -> iteration -> field_name -> value

    Only terminal InputSteps contribute values.
    """
    context_inputs: dict[KeyPath, dict[int, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    # Count repeats per (context_path, input_field_path)
    seen: dict[tuple[KeyPath, KeyPath], int] = defaultdict(int)

    for ui in inputs:
        step = ui.input_step

        # Root-level fields belong to ()
        if isinstance(step.parent, SessionStart):
            ctx_path = ()
        else:
            ctx_path = step.parent.field.path

        iteration = seen[(ctx_path, step.field.path)]
        seen[(ctx_path, step.field.path)] += 1

        context_inputs[ctx_path][iteration][step.name] = ui.value

    return context_inputs


def _iter_root_children(start: SessionStart) -> Iterator[SessionStep]:
    cur = start.next
    while cur:
        if isinstance(cur, (InputStep, ContextEntry)) and cur.parent is start:
            yield cur
        cur = cur.next


def _iter_context_children(context: ContextEntry) -> Iterator[SessionStep]:
    """
    Yield the direct children of `context` in traversal order.

    IMPORTANT:
    There may be RepeatExit nodes for *nested* schema containers.
    We must only stop at the RepeatExit that belongs to THIS context.
    """
    cur = context.next
    while cur:
        # Only stop if this RepeatExit closes *this* context (schema container)
        if isinstance(cur, RepeatExit):
            if cur.parent is context:
                break
            # RepeatExit for a nested container: ignore and keep scanning
            cur = cur.next
            continue

        if isinstance(cur, (InputStep, ContextEntry)):
            if cur.parent is context:
                yield cur
            elif not is_child_path(context.field.path, cur.field.path):
                break

        cur = cur.next


def _wrap_unaliased(
    fld: NormalizedField[
        ContainerShape | FixedContainerShape | SchemaContainerShape
    ],
    to_wrap: Any,
) -> Any:
    if fld.type_non_aliased_base != fld.shape.container_type:
        return fld.type_non_aliased_base(to_wrap)
    return to_wrap
