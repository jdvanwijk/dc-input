# dc-input

[![PyPI](https://img.shields.io/pypi/v/dc-input.svg)](https://pypi.org/project/dc-input/)
[![License](https://img.shields.io/github/license/jdvanwijk/dc-input.svg)](LICENSE)

**Interactively fill dataclass instances via the command line.** 
Features include nested schemas, repeatable containers, undo support, defaults, optional fields, and custom parsers.
Useful for quick data entry, prototyping, or structured configuration; integrates easily with your own CLI tools.
---
## Installation
```bash
pip install dc-input
```
---

## Usage
Define your dataclasses as usual, then call `get_input()` to interactively collect values:
```python
from __future__ import annotations

from dataclasses import dataclass
import datetime
from pprint import pprint
import re
from typing import Annotated

from dc_input import get_input


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
    start_date: Annotated[datetime.date | None, "DD/MM/YY"]
    comments: str | None


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
```
## Interactive Session Example
```
# Type '..' to undo previous input
# Press 'enter' to skip fields marked with ?

[name <- music student]
first : Jakob
middle? <str, ...> : Ludwig, Felix
last : Mandelssohn Bartholdy

[music student]
date of birth <date: DD/MM/YYYY> : ..

[name <- music student]
last : Mendelssohn Bartholdy

[music student]
date of birth <date: DD/MM/YYYY> : 03/02/1809

[address <- music student]
# Must be a German address
street : Jägerstraße
street number <int> : 51
apartment? : 
zip code <int: XXXXX> : 10117
city : (default: Berlin) 

[primary instrument <- music student]
name : piano
start date? <date: DD/MM/YY> : 01/01/1816
comments? : 

# Other instruments the student may have experience with
> Add secondary instruments to music student? <y/n> : y

[instrument <- music student]
name : violin
start date? <date: DD/MM/YY> : 
comments? : 

> Add another instrument to music student? <y/n> : y

[instrument <- music student]
name : ukelele
start date? <date: DD/MM/YY> : 
comments? : student proclaimed 'uke is life', look up what that means

> Add another instrument to music student? <y/n> : n

[music student]
comments? : seems v. talented

> Finish? <y/n> : y
```
## Final Result
TODO
---
## Planned Features
- Adapters for `attrs`, `pydantic` and `sqlalchemy` 
- Customizable UX