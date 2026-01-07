"""Unit tests for parse and _coerce functions."""

import pytest
from typing import Annotated, Any, Literal, Optional

from dc_input._errors import InputError
from dc_input._pipeline.run_user_session._parse_input import (
    parse_input,
    _is_container_type,
    _select_parser,
)
from dc_input._pipeline.merge_parsers import _get_primitive_parsers


# TODO: REDO TESTS


@pytest.fixture
def default_registry():
    """Return the default parser registry."""
    return _get_primitive_parsers()


def test_annotated(default_registry):
    assert parse_input("hello", Annotated[str, "metadata"], default_registry) == "hello"


def test_any(default_registry):
    assert parse_input("anything", Any, default_registry) == "anything"


class TestLiteralTypes:
    """Test parsing of Literal types."""

    def test_literal_str(self, default_registry):
        assert parse_input("red", Literal["red", "green", "blue"], default_registry) == "red"

    def test_literal_int(self, default_registry):
        assert parse_input("1", Literal[1, 2, 3], default_registry) == 1


class TestOptionalTypes:
    """Test parsing of Optional types."""

    def test_optional_flat_not_none(self, default_registry):
        assert parse_input("hello", Optional[str], default_registry) == "hello"

    def test_optional_flat_none(self, default_registry):
        assert parse_input("none", Optional[str], default_registry) is None

    def test_optional_nested_not_none(self, default_registry):
        assert parse_input("1,2,3", Optional[list[int]], default_registry) == [1, 2, 3]

    def test_optional_nested_none(self, default_registry):
        assert parse_input("none", Optional[list[int]], default_registry) is None


class TestListSetTypes:
    """Test parsing of list and set types."""

    def test_list_int(self, default_registry):
        assert parse_input("1,2,3", list[int], default_registry) == [1, 2, 3]

    def test_list_str(self, default_registry):
        assert parse_input("a,b,c", list[str], default_registry) == ["a", "b", "c"]

    def test_list_nested(self, default_registry):
        assert parse_input("a,(b,c),d", list[Any], default_registry) == ["a", ["b", "c"], "d"]

    def test_list_deeply_nested(self, default_registry):
        assert parse_input("((a,b),(c,d))", list[list[list[str]]], default_registry) == [
            [["a", "b"], ["c", "d"]]
        ]

    def test_set(self, default_registry):
        assert parse_input("a,b,c,a", set[str], default_registry) == {"a", "b", "c"}


class TestTupleTypes:
    """Test parsing of tuple types."""

    def test_tuple_fixed_length(self, default_registry):
        assert parse_input("1,hello,true", tuple[int, str, bool], default_registry) == (
            1,
            "hello",
            True,
        )

    def test_tuple_variable_length(self, default_registry):
        assert parse_input("1,2,3,4,5", tuple[int, ...], default_registry) == (1, 2, 3, 4, 5)

    def test_tuple_any(self, default_registry):
        assert parse_input("1,hello,3.14", tuple, default_registry) == ("1", "hello", "3.14")


class TestDictTypes:
    """Test parsing of dict types."""

    def test_dict_str_int(self, default_registry):
        assert parse_input("(a,1),(b,2),(c,3)", dict[str, int], default_registry) == {
            "a": 1,
            "b": 2,
            "c": 3,
        }

    def test_dict_nested_value(self, default_registry):
        assert parse_input(
            "(key1,(a,b)),(key2,(c,d))", dict[str, list[str]], default_registry
        ) == {"key1": ["a", "b"], "key2": ["c", "d"]}


class TestStrip:
    def test_str_with_spaces(self, default_registry):
        assert parse_input("  test    ", str, default_registry) == "test"

    def test_list_with_spaces(self, default_registry):
        assert parse_input("  a , b ,  c  ", list[str], default_registry) == ["a", "b", "c"]


class TestEscape:
    def test_escape_comma(self, default_registry):
        assert parse_input(r"a\,b", str, default_registry) == "a,b"

    def test_escape_parentheses(self, default_registry):
        assert parse_input(
            r"a, (b, c), \(not nested\)",
            tuple[str, tuple[str, ...], str],
            default_registry,
        ) == (
            "a",
            ("b", "c"),
            "(not nested)",
        )


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_container_type(self):
        assert _is_container_type(list) is True
        assert _is_container_type(dict) is True
        assert _is_container_type(set) is True
        assert _is_container_type(tuple) is True
        assert _is_container_type(str) is False
        assert _is_container_type(int) is False

    def test_select_parser(self, default_registry):
        # Test registry lookup
        parser = _select_parser(str, default_registry)
        assert parser("test") == "test"

        # Test MRO fallback
        class MyStr(str):
            pass

        parser = _select_parser(MyStr, default_registry)
        assert parser is default_registry[str]

        # Test default constructor
        class CustomClass:
            def __init__(self, value):
                self.value = value

        parser = _select_parser(CustomClass, default_registry)
        result = parser("test")
        assert isinstance(result, CustomClass)


class TestInvalidInput:
    def test_literal_invalid(self, default_registry):
        with pytest.raises(InputError):
            parse_input("yellow", Literal["red", "green", "blue"], default_registry)

    def test_list_invalid_element(self, default_registry):
        with pytest.raises(InputError):
            parse_input("1,not_a_number,3", list[int], default_registry)

    def test_list_unmatched_opening_parenthesis(self, default_registry):
        with pytest.raises(InputError):
            parse_input("a, (b", list[str], default_registry)

    def test_list_unmatched_closing_parenthesis(self, default_registry):
        with pytest.raises(InputError):
            parse_input("3, 4)", list[int], default_registry)

    def test_tuple_length_mismatch_too_few(self, default_registry):
        with pytest.raises(InputError):
            parse_input("1,hello", tuple[int, str, bool], default_registry)

    def test_tuple_length_mismatch_too_many(self, default_registry):
        with pytest.raises(InputError):
            parse_input("1,hello,true,4", tuple[int, str, bool], default_registry)

    def test_dict_invalid_pair(self, default_registry):
        with pytest.raises(InputError):
            parse_input("(a,1),(b)", dict[str, int], default_registry)

    def test_dict_missing_parenthesis(self, default_registry):
        with pytest.raises(InputError):
            parse_input("key1,value1", dict[str, str], default_registry)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
