from __future__ import annotations

from dataclasses import dataclass, field, asdict
import datetime
import json
import os
from pathlib import Path
from pprint import pprint
import re
import tempfile
from typing import Annotated

from _get_input import get_input

STUDENTS_PATH = Path("students.json")

# ------------------------------------------------------------
# Schema
# ------------------------------------------------------------
@dataclass
class MusicStudent:
    id: int

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


@dataclass
class Instrument:
    name: str
    start_date: Annotated[datetime.date | None, "DD/MM/YYYY"]
    comment: str | None


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def parse_date_dmy(s: str) -> datetime.date:
    s_normalized = s.strip().replace(".", "/").replace("-", "/")
    date = "/".split(s_normalized)
    try:
        day = int(date[0])
        month = int(date[1])
        year = int(date[2])
    except Exception:
        raise ValueError("wrong format, must be DD/MM/YYYY")
    else:
        return datetime.date(year, month, day)


def json_default(obj):
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    raise TypeError(f"Type not serializable: {type(obj)}")


# ------------------------------------------------------------
# Main function
# ------------------------------------------------------------
if __name__ == "__main__":
    # Get input
    parsers = {
        datetime.date: parse_date_dmy,
    }
    res = get_input(MusicStudent, parsers=parsers)
    res_dict = asdict(res)  # dataclasses → JSON-serializable dict

    # Deserialize student registry
    data: dict[str, list] = {"students": []}
    if STUDENTS_PATH.exists():
        with open(STUDENTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

    # Add session result to deserialized registry
    data.setdefault("students", [])
    data["students"].append(res_dict)

    # Serialize registry back to JSON and overwrite old file
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=STUDENTS_PATH.parent
    ) as tmp:
        json.dump(data, tmp, indent=2, default=json_default)
        tmp_name = tmp.name

    os.replace(tmp_name, STUDENTS_PATH)

    # Done
    print("\nNew student added:")
    pprint(res)
    print(f"\nSaved to {STUDENTS_PATH.name}")
