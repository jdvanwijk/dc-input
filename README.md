# data-cli

[![PyPI](https://img.shields.io/pypi/v/data-cli.svg)](https://pypi.org/project/data-cli/)
[![License](https://img.shields.io/github/license/yourusername/data-cli.svg)](LICENSE)

A tiny, dependency-free library that lets you **interactively fill dataclass instances** via the command line.
Perfect for quick data entry, prototyping, or structured configuration.
---

## Features
- Supports defaults and nested dataclasses
- Supports custom parsers
- Automatically structures prompts to flow naturally through nested structures
---

## Installation
```bash
pip install data_cli
```
---

## Usage

```python
from dataclasses import dataclass
from datetime import date

from data_cli import from_dataclass


# --- Setup custom parsers as required  ---
def _parse_bool(s: str) -> bool:
    if s.lower() in ("y", "yes", "1", "true", "t"):
        return True
    elif s.lower() in ("n", "no", "0", "false", "f"):
        return False
    raise ValueError(f"Can't parse {s!r}")


parsers = {
    bool: _parse_bool,
    date: lambda s: date.fromisoformat(s)
}


# --- Example dataclass schema with nesting and defaults ---
@dataclass
class Address:
    city: str
    postal_code: str
    country: str = "Germany"


@dataclass
class Employee:
    name: str
    birthdate: date
    address: Address
    active: bool = True


# --- Use the CLI to fill in all values interactively ---
if __name__ == "__main__":
    employee = from_dataclass(Employee, parsers=parsers)

    print("\n--- Final result ---")
    print(employee)
```
## Interactive Session Example
```
name (str): Alice
birthdate (date): 1982-07-08
active (bool, default=True): 0

address.city (str): Beriln    
address.postal_code (str): ..   > 💡 Undo previous input.

address.city (str): Berlin
address.postal_code (str): 10084
address.country (str, default=Germany):   > 💡 Accept default value.

New data:   > 💡 Edit values as needed. 
[0] name (str): Alice
[1] birthdate (date): 1982-07-08
[2] active (bool): False
[3] address.city (str): Berlin
[4] address.postal_code (str): 10084
[5] address.country (str): Germany

Change value? (n / {index} {new_value}): 4 10085

New data:
[0] name (str): Alice
[1] birthdate (date): 1982-07-08
[2] active (bool): False
[3] address.city (str): Berlin
[4] address.postal_code (str): 10085
[5] address.country (str): Germany

Change value? (n / {index} {new_value}): n   > 💡 Session complete.
```
## Final Result
```python
Employee(
    name='Alice', 
    birthdate=datetime.date(1982, 7, 8), 
    address=Address(
        city='Berlin', 
        postal_code='10085', 
        country='Germany'
    ), 
    active=False
)
```
---
## Planned Features
- Support for `attrs` and `pydantic`
- Optional JSON/YAML import/export
- Better colorized CLI output
