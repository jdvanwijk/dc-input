These invariants define the contracts between pipeline stages. Tests are written against these contracts; if they hold, higher-level behavior is expected to be correct.

# User definitions
**Validated in:** `_pipeline/validate_user_definitions.py`

## General rules
- **Rule:** Parsing must be unambiguous
  - *Why:* Session result should be deterministic
  - *Example:* `int | str` is invalid - should the parser choose `int` or `str`?

- **Rule:** End users should never have to write nested parentheses
  - *Why:* Would result in poor UX, we can't assume that the end user is a programmer

- **Rule:** End users should never feel disoriented within the input graph
  - *Why:* The library’s UX depends on maintaining orientation across nested structures

- **Rule:** Users may use subclasses of builtins
  - *Why:* Easier integration with existing user schemas
  - *Implications:* Never switch on `T is U`; always check whether `T` is a subclass of `U`
  - *Notes:* Use `alt_issubclass` from `_pipeline/_utils.py` for subclass checks

---

## Schema
**Validated in:** `_pipeline/validate_user_definitions.py::_get_schema_errors`

- **Rule:** A schema must be a dataclass
  - *Why:* Dataclasses require type hints, which are needed for parsing input values

- **Rule:** A schema must have at least one field
  - *Why:* An empty schema cannot produce an interactive session


### Union

- **Rule:** Unions must represent optionality only (`T | None` or `Optional[T]`)
  - *Why:* Prevents ambiguity when parsing input values
  - *Notes:* Both forms are accepted but normalized to a single internal representation

- **Rule:** Unions must not be nested inside containers
  - *Why:* Within a container, users lack the context needed to interpret optionality
  - *Example:* `list[T | None]` is invalid

### Dict

- **Rule:** Schemas are not allowed as values
  - *Why:* Users easily lose track of their position in the input graph; named fields provide better orientation

- **Rule:** `dict`, `list`, `set`, and `tuple` are not allowed as values
  - *Why:* Requires nested parentheses, which quickly become unreadable
  - *Example:* `dict[str, list[str]]` would be expressed as `<(str, (str, ...))>`

### List / Set / Tuple

- **Rule:** Without a schema, containers may nest at most one level
  - *Why:* Deeper nesting requires nested parentheses
  - *Example:* `list[list[T]]` is valid; `list[list[list[T]]]` is invalid

- **Rule:** With a schema, nesting is not allowed
  - *Why:* Deeply nested schema containers are confusing and make it easy for users to lose their bearing
  - *Example:* `list[Schema]` is valid; `list[list[Schema]]` is invalid

### Set

- **Rule:** Schemas used in `set` must be declared with `frozen=True`
  - *Why:* Set elements must be hashable; unhashable schemas would fail during reconstruction, resulting in poor UX

### Fixed-size Tuple with schemas

- **Rule:** Must be homogeneous
  - *Why:* Mixed schema tuples would be disorienting for the end user

- **Rule:** Must contain at least two schemas
  - *Why:* `tuple[Schema]` is redundant; users should declare a bare `Schema` instead
  - *Notes:* This rule may be relaxed in the future if a strong use case emerges

### Annotated

- **Rule:** `Annotated` must not be nested inside another type
  - *Why:* Adds parsing complexity without providing practical benefits
  - *Example:* `list[Annotated[T]]` is invalid; use `Annotated[list[T]]` instead

### None / NoneType

- **Rule:** Field types must not be `NoneType`
  - *Why:* A field with type `None` / `NoneType` has no semantic meaning in an interactive session

---

## Container alias registry
**Validated in:** `_pipeline/validate_user_definitions.py::_get_container_registry_errors`

A container alias registry maps a *custom container type* to a *concrete builtin container implementation* that the system knows how to parse (e.g. alias `MyList` → `list[str]` or `list`).

- **Rule:** The registry must be a `dict`
  - *Why:* The system expects `dict.items()` semantics and deterministic key → value mappings

- **Rule:** Registry keys must be **concrete, non-parameterized types**
  - *Why:* Parameterized types are not stable runtime keys and are hard to reason about in user APIs
  - *Implications:* Use the class (e.g. `MyList`), not `MyList[int]`
  - *Example:* `MyList[int]` as a key is invalid

- **Rule:** Registry values must be concrete types or parameterized types
  - *Why:* Alias resolution inspects the value’s base type and type arguments


- **Rule:** Alias values must satisfy the same “type shape” constraints as schema fields.
  - *Why:* Alias value is used exactly as a 'normal' type hint

- **Rule:** Alias values must be subclasses of `dict`, `list`, `set`, or `tuple`
  - *Why:* The input system only knows how to parse these container families
  - *Implications:* If you want custom parsing, use a custom leaf parser instead of a container alias
  - *Example:* aliasing to `collections.deque` is invalid unless it subclasses one of the supported families

---

## ParserRegistry

**Validated in:** `_pipeline/validate_user_definitions.py::_get_parser_registry_errors`

A parser registry maps **concrete leaf types** to parser functions used by the input system.

- **Rule:** The registry must be a `dict`
  - *Why:* The system expects `dict.items()` semantics and deterministic type → parser lookup

- **Rule:** Registry keys must be **concrete, non-parameterized types**
  - *Why:* Parsers are looked up by runtime type; parameterized types are not stable lookup keys
  - *Example:* `list[int]` is invalid as a key
  - *Example:* `datetime.date` is valid as a key

- **Rule:** Registry values must be callable
  - *Why:* Parsers are invoked as functions during input parsing
  - *Implications:* A parser should raise a descriptive exception (e.g. `ValueError`) on invalid input

- **Rule:** Parsers must not be registered for “built-in parsing domain” types (primitives, containers, or typing abstractions)
  - *Why:* Overriding these would break core parsing semantics and/or conflict with the type-shape rules
  - *Implications:* If you want custom behavior for `int`/`list`/`Union` etc., that’s currently out of scope by design
  - *Notes:* Disallowed bases include: `str`, `int`, `float`, `bool`, `NoneType`, `list`, `set`, `tuple`, `dict`, and typing constructs like `Any`, `Literal`, `Annotated`, `Union` / `UnionType`, and their `typing.*` aliases


