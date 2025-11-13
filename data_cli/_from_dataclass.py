from collections import defaultdict
from collections.abc import Iterator, Iterable, MutableMapping, Callable
from dataclasses import fields, is_dataclass, Field, MISSING
from typing import ClassVar, Any, cast


class DataclassInstance:
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


KeyPath = tuple[Field, ...]
Parsers = dict[type, Callable[[str], object]]
Result = dict[Field, dict | object]
Schema = type[DataclassInstance]


def _rgetitem[T](d: MutableMapping[T, object], ks: Iterable[T]) -> object:
    """Get item through an iterable of keys"""
    tmp = d
    for k in ks:
        tmp = tmp[k]

    return tmp


def _rsetitem[T](d: MutableMapping[T, object], ks: Iterable[T], v: object) -> None:
    """Set item through an iterable of keys"""
    ks = list(ks)
    tmp = d
    for i, k in enumerate(ks):
        if i == len(ks) - 1:
            tmp[k] = v
        else:
            tmp = tmp[k]


def _flatten_schema(schema: Schema) -> list[KeyPath]:
    def yield_item(s: Schema, _prefix: KeyPath = ()) -> Iterator[KeyPath]:
        nested: list[tuple[Schema, KeyPath]] = []
        for f in fields(cast(Any, s)):              # stub does not include Type[DataclassInstance]
            path = _prefix + (f,)
            yield path
            if is_dataclass(f.type):
                nested.append((f.type, path))
        # Put nested schemas at the end of each node for better query flow
        for s, ks in nested:
            yield from yield_item(s, ks)

    return list(yield_item(schema))


def _parse_input(s: str, t: type, parsers: Parsers | None = None) -> object:
    if p := parsers.get(t):
        return p(s)
    return t(s)


def _dict_to_dataclass[T](cls: type[T], data: Result) -> T:
    kwargs = {}
    for f in fields(cls):
        v = data.get(f)
        if is_dataclass(f.type):
            v = _dict_to_dataclass(f.type, v)
        kwargs[f.name] = v
    return cls(**kwargs)


def from_dataclass[T](schema: type[T], *, parsers: Parsers | None = None) -> T:
    if not is_dataclass(schema):
        raise ValueError("Provided schema must be a dataclass.")

    flat = _flatten_schema(schema)
    leaves = [ks for ks in flat if not is_dataclass(ks[-1].type)]
    result = defaultdict(dict)
    for ks in flat:
        v = {} if is_dataclass(ks[-1].type) else None
        _rsetitem(result, ks, v)

    i = 0
    while i < len(leaves):
        ks = leaves[i]

        # Print newline when next node
        if i > 0:
            ks_prev = leaves[i - 1]
            if ks_prev[:-1] != ks[:-1]:
                print()

        # Query user for field value
        default = getattr(ks[-1], "default", MISSING)
        def_prompt = f", default={default}" if default is not MISSING else ""
        v = input(f"{".".join(k.name for k in ks)} ({ks[-1].type.__name__}{def_prompt}): ").strip()

        # Undo previous input (optional)
        if v == "..":
            if i == 0:
                print("Nothing to undo.")
            else:
                i -= 1
            continue

        # Parse value and add to result
        try:
            if v == "" and default is not MISSING:
                v = default
            else:
                v = _parse_input(v, ks[-1].type, parsers)
        except ValueError:
            print("> Invalid input.")
            continue
        else:
            _rsetitem(result, ks, v)
            i += 1

    # Final check if all input is correct
    while True:
        print("\nNew data:")
        for i, ks in enumerate(leaves):
            v = _rgetitem(result, ks)
            print(f"[{i}] {".".join(k.name for k in ks)} ({ks[-1].type.__name__}): {v}")

        ch = input("\nChange value? (n / {index} {new_value}): ").strip()
        if ch.lower() == "n":
            break
        try:
            i, v = ch.split()
            ks = leaves[int(i)]
            v = _parse_input(v, ks[-1].type, parsers)
            _rsetitem(result, ks, v)
        except ValueError:
            print("> Invalid input.")
            continue
        except IndexError:
            print("> Invalid index.")

    return _dict_to_dataclass(schema, result)
