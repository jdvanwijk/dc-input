from collections import defaultdict
from dataclasses import is_dataclass
from pprint import pprint
from typing import TypeVar, Any

from dc_input._types import UserInput, SessionStart, InputStep, KeyPath, SessionEnd, ContextEntry, SchemaContainerShape
from dc_input._utils import is_child_path

T = TypeVar("T")


def initialize_schema(schema: type[T], inputs: list[UserInput]) -> T:
    assert is_dataclass(schema)
    assert inputs
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
    #     assert isinstance(cur, (InputStep, ContextEntry))
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
    # initialized: list[Any] = []
    # node_paths_to_process = list(nodes.keys())
    # processed_node_paths: list[KeyPath] = []
    # # while processed_node_paths != list(nodes.keys()):
    # #     for path_cur, node in nodes.items():
    # #         if path_cur in processed_node_paths:
    # #             continue
    # #         elif any(_is_child_path(path_cur, path) for path in node_paths_to_process):
    # #             continue
    # #
    # #         data = input_values[path_cur]
    # #         if isinstance(node.field.shape, SchemaContainerShape):
    # #            pass
    #
    #
    # pprint(nodes)
    # pprint(input_values)

    # create tree structure using paths
    # serialize tree into obj

    return inputs

# def _initialize(initialized: list[Any] | None = None, to_process: )
