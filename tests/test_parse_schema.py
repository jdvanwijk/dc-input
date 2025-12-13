import pytest
from dataclasses import dataclass, is_dataclass, field
from typing import Union

from dc_input._errors import SchemaError
from dc_input._parse_schema import parse_schema


class TestInvalidSchema:
    def test_non_dataclass(self):
        class Invalid:
            pass

        with pytest.raises(SchemaError):
            parse_schema(Invalid)

    def test_union_non_optional(self):
        @dataclass
        class Invalid:
            a: Union[str, int]

        with pytest.raises(SchemaError):
            parse_schema(Invalid)

    def test_union_multiple_non_none(self):
        @dataclass
        class Invalid:
            a: Union[str, int, None]

        with pytest.raises(SchemaError):
            parse_schema(Invalid)


def test_simple_schema():
    @dataclass
    class Simple:
        name: str
        age: int

    sc_dict, metadata = parse_schema(Simple)

    # sc_dict has string keys at each level
    assert "name" in sc_dict
    assert "age" in sc_dict

    # metadata has tuple paths for all fields
    assert ("name",) in metadata
    assert ("age",) in metadata
    assert metadata[("name",)].name == "name"


def test_nested_schema():
    @dataclass
    class Inner:
        value: str

    @dataclass
    class Outer:
        name: str
        inner: Inner

    sc_dict, metadata = parse_schema(Outer)

    # sc_dict structure
    assert "name" in sc_dict
    assert "inner" in sc_dict
    assert isinstance(sc_dict["inner"], dict)
    assert "value" in sc_dict["inner"]

    # metadata paths
    assert ("name",) in metadata
    assert ("inner",) in metadata
    assert ("inner", "value") in metadata
    assert metadata[("inner",)].type == Inner
    assert metadata[("inner", "value")].name == "value"


def test_deeply_nested_schema():
    @dataclass
    class Level3:
        deep: int

    @dataclass
    class Level2:
        middle: str
        level3: Level3

    @dataclass
    class Level1:
        top: bool
        level2: Level2

    sc_dict, metadata = parse_schema(Level1)

    # Check nested dict structure
    assert isinstance(sc_dict["level2"]["level3"], dict)
    assert "deep" in sc_dict["level2"]["level3"]

    # Check metadata paths
    assert ("top",) in metadata
    assert ("level2",) in metadata
    assert ("level2", "middle") in metadata
    assert ("level2", "level3") in metadata
    assert ("level2", "level3", "deep") in metadata
    assert metadata[("level2", "level3", "deep")].name == "deep"


def test_default_values():
    @dataclass
    class Schema:
        name: str = "default"
        count: int = 0
        items: list[str] = field(default_factory=list)

    sc_dict, metadata = parse_schema(Schema)

    assert metadata[("name",)].default == "default"
    assert metadata[("count",)].default == 0
    assert metadata[("items",)].default_factory is list


def test_leaves_in_metadata_before_nodes():
    @dataclass
    class InnerInner:
        val: str

    @dataclass
    class Inner:
        node: InnerInner
        inner_val: str

    @dataclass
    class Outer:
        leaf1: str
        node: Inner
        leaf2: int

    _, mdata_dict = parse_schema(Outer)
    mdata_fields = list(mdata_dict.values())

    assert not any(is_dataclass(mdata.type) for mdata in mdata_fields[:2])
    assert is_dataclass(mdata_fields[2].type)
    assert not is_dataclass(mdata_fields[3].type)
    assert is_dataclass(mdata_fields[4].type)
    assert not is_dataclass(mdata_fields[5].type)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
