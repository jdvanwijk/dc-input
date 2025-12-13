from types import NoneType
from typing import Optional, Union, Annotated

from dc_input._utils import get_type_base_args


def test_get_type_info():
    assert get_type_base_args(str) == (str, ())
    assert get_type_base_args(list[int]) == (list, (int,))
    assert get_type_base_args(Optional[str]) == (Union, (str, NoneType))
    assert get_type_base_args(Annotated[str, "meta"]) == (Annotated, (str, "meta"))