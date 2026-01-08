import dataclasses
from collections import defaultdict
from dataclasses import is_dataclass
from pprint import pprint
from typing import TypeVar, Any

from dc_input._types import UserInput, SessionStart, InputStep, KeyPath, SessionEnd, ContextEntry, SchemaContainerShape, \
    RepeatExit, SchemaShape, NormalizedField, SessionStep
from dc_input._utils import is_child_path, get_type_base_args

T = TypeVar("T")


def initialize_schema(schema: type[T], inputs: list[UserInput]) -> T:
    assert inputs
    assert is_dataclass(schema)

    # Find SessionStart
    cur = inputs[0].input_step
    while not isinstance(cur, SessionStart):
        cur = cur.parent
    start = cur

    context_inputs = collect_context_inputs(inputs)

    # Root behaves like a context with path ()
    children = list(iter_root_children(start))

    return build_context_instance(
        schema_type=schema,
        ctx_path=(),
        children=children,
        context_inputs=context_inputs,
        iteration=0,
    )


    # assert is_dataclass(schema)
    # assert inputs
    #
    # graph_start = inputs[0].input_step.parent
    # while not isinstance(
    #     graph_start, SessionStart
    # ):  # Case: first graph_step after GraphStart is Node
    #     graph_start = graph_start.parent
    #
    # nodes: dict[KeyPath, ContextEntry] = {}
    # cur = graph_start.next
    # while not isinstance(cur, SessionEnd):
    #     if isinstance(cur, ContextEntry):
    #         nodes[cur.field.path] = cur
    #     cur = cur.next
    #
    # input_values: dict[KeyPath, dict[int, dict[str, Any]]] = defaultdict(
    #     lambda: defaultdict(dict)
    # )
    # seen_paths: dict[KeyPath, int] = {}
    # for inpt in inputs:
    #     inpt_key = inpt.input_step.name
    #     inpt_path = inpt.input_step.field.path
    #     if isinstance(inpt.input_step.parent, SessionStart):
    #         node_path = ()
    #     else:
    #         node_path = inpt.input_step.parent.field.path
    #
    #     if inpt_path in seen_paths:
    #         n_repeat = seen_paths[inpt_path] + 1
    #     else:
    #         n_repeat = 0
    #     seen_paths[inpt_path] = n_repeat
    #
    #     input_values[node_path][n_repeat][inpt_key] = inpt.value
    #
    # print(input_values)

    # initialized: list[Any] = []
    # node_paths_to_process = list(nodes.keys())
    # processed_node_paths: list[KeyPath] = []
    # while processed_node_paths != list(nodes.keys()):
    #     for path_cur, node in nodes.items():
    #         if path_cur in processed_node_paths:
    #             continue
    #         elif any(is_child_path(path_cur, path) for path in node_paths_to_process):
    #             continue
    #
    #         data = input_values[path_cur]
    #         if isinstance(node.field.shape, SchemaContainerShape):
    #            pass


    pprint(input_values)


    return inputs

def build_repeated_context(
    ctx: ContextEntry,
    context_inputs,
):
    ctx_path = ctx.field.path
    iterations = context_inputs.get(ctx_path, {})

    children = list(iter_context_children(ctx))
    schema_type = ctx.field.shape.schema_type

    return [
        build_context_instance(
            schema_type=schema_type,
            ctx_path=ctx_path,
            children=children,
            context_inputs=context_inputs,
            iteration=i,
        )
        for i in sorted(iterations)
    ]

def build_context(
    ctx: ContextEntry,
    context_inputs,
):
    schema_type = ctx.field.shape.schema_type
    ctx_path = ctx.field.path

    iterations = context_inputs.get(ctx_path, {0: {}})
    children = list(iter_context_children(ctx))

    instances = [
        build_context_instance(
            schema_type=schema_type,
            ctx_path=ctx_path,
            children=children,
            context_inputs=context_inputs,
            iteration=i,
        )
        for i in sorted(iterations)
    ]

    return instances if len(instances) > 1 else instances[0]

def build_context_instance(
    *,
    schema_type: type,
    ctx_path: KeyPath,
    children: list[SessionStep],
    context_inputs,
    iteration: int,
):
    values = {}
    inputs = context_inputs.get(ctx_path, {}).get(iteration, {})

    for child in children:
        field = child.field
        name = child.name

        # ── Nested schema ─────────────────────────────
        if isinstance(child, ContextEntry) and isinstance(field.shape, SchemaShape):
            values[name] = build_context(
                child,
                context_inputs,
            )

        # ── Repeated schema ───────────────────────────
        elif isinstance(field.shape, SchemaContainerShape):
            container_t, _ = get_type_base_args(child.field.shape.container_type)
            res = container_t(build_repeated_context(
                child,
                context_inputs,
            ))

            # Handle registered container aliases
            unaliased_container_t, _ = get_type_base_args(child.field.type)
            if unaliased_container_t != container_t:
                res = unaliased_container_t(res)

            values[name] = res

        # ── Terminal input ────────────────────────────
        else:
            if name in inputs:
                values[name] = inputs[name]
            elif field.default is not dataclasses.MISSING:
                values[name] = field.default
            elif field.default_factory is not dataclasses.MISSING:
                values[name] = field.default_factory()
            elif field.is_optional:
                values[name] = None
            else:
                raise ValueError(f"Missing required field {field.path}")

    return schema_type(**values)

def iter_root_children(start: SessionStart):
    cur = start.next
    while cur:
        if isinstance(cur, (InputStep, ContextEntry)) and cur.parent is start:
            yield cur
        cur = cur.next


def iter_context_children(ctx: ContextEntry):
    cur = ctx.next
    while cur:
        if isinstance(cur, RepeatExit):
            break

        if isinstance(cur, (InputStep, ContextEntry)):
            if cur.parent is ctx:
                yield cur
            elif not is_child_path(ctx.field.path, cur.field.path):
                break

        cur = cur.next


from collections import defaultdict

def collect_context_inputs(inputs: list[UserInput]):
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
