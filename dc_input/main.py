from __future__ import annotations

from dataclasses import dataclass, field
import datetime
from pprint import pprint
import re
from typing import Annotated

from dc_input._get_input import get_input


@dataclass
class MusicStudent:
    name: Name
    date_of_birth: Annotated[datetime.date, "DD/MM/YYYY"]
    address: Annotated[Address, "Must be a German address"]

    primary_instrument: Instrument
    secondary_instruments: Annotated[
        list[Instrument], "Other instruments the student may have experience with"
    ]

    comments: str | None


@dataclass
class Name:
    first: str
    middle: list[str]
    last: str

    full: str = field(init=False)

    def __post_init__(self):
        middle = f" {' '.join(name for name in self.middle)} " if self.middle else " "
        self.full = f"{self.first}{middle}{self.last}"


@dataclass
class Address:
    street: str
    street_number: int
    apartment: str | None
    zip_code: Annotated[int, "XXXXX"]
    city: str = "Berlin"


@dataclass(kw_only=True)
class Instrument:
    name: str
    start_date: Annotated[datetime.date | None, "DD/MM/YY"]
    comment: str | None


def parse_date_dmy(s: str) -> datetime.date:
    match = re.match(
        r"(?P<day>\d{1,2})[\-./](?P<month>\d{1,2})[\-./](?P<year>\d{4})$", s.strip()
    )
    try:
        day = int(match.group("day"))
        month = int(match.group("month"))
        year = int(match.group("year"))
    except Exception:
        raise ValueError("wrong format")
    else:
        return datetime.date(year, month, day)


if __name__ == "__main__":
    parsers = {
        datetime.date: parse_date_dmy,
    }

    res = get_input(MusicStudent, parsers=parsers)
    pprint(res)
