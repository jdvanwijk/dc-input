from collections import defaultdict
from collections.abc import Iterator
from dataclasses import is_dataclass
from typing import TypeVar, Any

from .._types import (
    UserInput,
    SessionStart,
    InputStep,
    KeyPath,
    ContextEntry,
    SchemaContainerShape,
    RepeatExit,
    SchemaShape,
    NormalizedField,
    SessionStep,
    FixedSchemaContainerShape,
    FixedContainerShape,
    ContainerShape,
)
from dc_input._pipeline._utils import is_child_path

T = TypeVar("T")


# ------------------------------------------------------------
# Main functions
# ------------------------------------------------------------
def initialize_schema(schema: type[T], inputs: list[UserInput]) -> T:
    assert inputs
    assert is_dataclass(schema)

    # Find SessionStart
    cur = inputs[0].input_step
    while cur.parent is not None:
        cur = cur.parent
    start = cur

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
    context_inputs: Any,
    iteration: int,
) -> Any:
    values = {}
    inputs = context_inputs.get(context_path, {}).get(iteration, {})

    for child in children:
        fld = child.field
        name = child.name

        # ── Nested schema ─────────────────────────────
        if isinstance(child, ContextEntry) and isinstance(fld.shape, SchemaShape):
            values[name] = _build_context(
                child,
                context_inputs,
            )

        # ── Repeated schema ───────────────────────────
        elif isinstance(fld.shape, SchemaContainerShape):
            res = fld.shape.container_type(
                _build_repeated_context(
                    child,
                    context_inputs,
                )
            )

            # Wrap in unaliased container type when necessary
            if fld.type_non_aliased_base != fld.shape.container_type:
                res = fld.type_non_aliased_base(res)

            values[name] = _wrap_unaliased(fld, res)

        # ── Terminal input ────────────────────────────
        else:
            inpt = inputs[name]
            if isinstance(fld.shape, (FixedContainerShape, FixedSchemaContainerShape)):
                container_t, _ = fld.shape.container_type
                assert isinstance(inpt, container_t)
                values[name] = _wrap_unaliased(fld, inputs[name])
            else:
                values[name] = inpt

    return schema_type(**values)


def _build_context(
    context: ContextEntry,
    context_inputs: Any,
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


def _build_repeated_context(context: ContextEntry, context_inputs: Any) -> Any:
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
    """
    context_inputs = defaultdict(lambda: defaultdict(dict))
    seen = defaultdict(int)

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


def _iter_root_children(start: SessionStart) -> Iterator[Any]:
    cur = start.next
    while cur:
        if isinstance(cur, (InputStep, ContextEntry)) and cur.parent is start:
            yield cur
        cur = cur.next


def _iter_context_children(context: ContextEntry) -> Iterator[Any]:
    cur = context.next
    while cur:
        if isinstance(cur, RepeatExit):
            break

        if isinstance(cur, (InputStep, ContextEntry)):
            if cur.parent is context:
                yield cur
            elif not is_child_path(context.field.path, cur.field.path):
                break

        cur = cur.next


def _wrap_unaliased(
    fld: NormalizedField[ContainerShape | FixedContainerShape | SchemaContainerShape],
    to_wrap: Any,
) -> Any:
    if fld.type_non_aliased_base != fld.shape.container_type:
        return fld.type_non_aliased_base(to_wrap)
    return to_wrap


# TODO [LOW]: See if I can make return types more precise, probably use Generics
