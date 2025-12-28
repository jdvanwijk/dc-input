from collections import defaultdict
from dataclasses import is_dataclass
from pprint import pprint

from dc_input._types import UserInput, GraphStart, Leaf, KeyPath, GraphEnd, Node
from typing import TypeVar, Any

T = TypeVar("T")


def parse_user_inputs(schema: type[T], inputs: list[UserInput]) -> T:
    assert is_dataclass(schema)
    assert inputs

    graph_start = inputs[0].graph_part.parent
    assert isinstance(graph_start, GraphStart)

    nodes: dict[KeyPath, Node] = {}
    cur = graph_start.next
    while not isinstance(cur, GraphEnd):
        assert isinstance(cur, (Leaf, Node))
        if isinstance(cur, Node):
            nodes[cur.field_name_path] = cur
        cur = cur.next

    input_values: dict[KeyPath, dict[int, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    seen_paths: dict[KeyPath, int] = {}
    for inpt in inputs:
        inpt_key = inpt.graph_part.name
        inpt_path = inpt.graph_part.field_name_path
        node_path = inpt.graph_part.parent.field_name_path
        if inpt_path in seen_paths:
            n_repeat = seen_paths[inpt_path] + 1
        else:
            n_repeat = 0
        seen_paths[inpt_path] = n_repeat

        input_values[node_path][n_repeat][inpt_key] = inpt.value

    pprint(nodes)
    pprint(input_values)


    # create tree structure using paths
    # serialize tree into obj

    return
