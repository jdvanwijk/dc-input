These invariants define the contracts between pipeline stages. Tests are written against these contracts; if they
hold, higher-level behavior is expected to be correct.

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
    - *Why:* Easier integration with existing user schemas, more inviting to users writing OOP code
    - *Implications:* Never switch on `T is U`; always check whether `T` is a subclass of `U`
    - *Notes:* Use `alt_issubclass` from `_pipeline/_utils.py` for subclass checks

## Schema

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

## Container alias registry

A container alias registry maps a *custom container type* to a *concrete builtin container implementation* that the
system knows how to parse (e.g. alias `MyList` → `list[str]` or `list`).

- **Rule:** Registry keys must be **concrete, non-parameterized types**
    - *Why:* Complicates parsing/reconstruction, without benefits
    - *Notes:* Values *are* allowed to be parameterized types

- **Rule:** Alias values must satisfy the same “type shape” constraints as schema fields.
    - *Why:* Alias value is used exactly as a 'normal' type hint

- **Rule:** Alias values must be subclasses of `dict`, `list`, `set`, or `tuple`
    - *Why:* The input system only knows how to parse these container families
    - *Notes:* If a valid use case arises, we might expand this

## Parser registry

A parser registry maps **concrete leaf types** to parser functions used by the input system.

- **Rule:** Registry keys must be **concrete, non-parameterized types**
    - *Why:* Parsers deal with leaf values which are almost never parameterized. Taking parameterization into account
      adds quite a bit of complexity.
    - *Notes:* If a valid use case arises, we might expand this

- **Rule:** Parsers must not be registered for built-in parsing domains (e.g. `int`, `str`, containers, `Union`, `Any`,
  etc.)
    - *Why:* Overriding these breaks core parsing semantics and conflicts with type-shape rules


- **Rule:** Registry values must be callable
    - *Why:* Parsers are invoked as functions during input parsing

- **Rule:** A parser should raise a descriptive exception (e.g. `ValueError`) on invalid input
    - *Why:* User needs actionable feedback on invalid input

---

# Normalized schema

**Produced in:** `_pipeline/normalize_schema.py`

Normalization converts a validated user schema (dataclasses + typing annotations) into a flat mapping:
`dict[KeyPath, NormalizedField]`
Each `NormalizedField` contains all metadata needed for graph construction and parsing, so later pipeline
stages do not need to re-introspect user types.

## Ordering

- **Rule:** The iteration order of the normalized schema follows the order of fields as declared in the user’s schema.
    - *Why:* Deterministic ordering is essential for predictable prompt order and reproducible sessions.

- **Rule:** When a field’s type contains a nested schema, that nested schema is normalized *immediately* at the point
  where the field is encountered.
    - *Why:* Preserves a natural, depth-first traversal that matches the user’s mental model of the schema.
    - *Implications:* Fields of nested schemas appear contiguously in the normalized schema, directly after the field
      that references them.

## Coverage

- **Rule:** Only dataclass fields with `init=True` are included
    - *Why:* `init=False` fields are not user-provided inputs and should not appear in the input session
    - *Implications:* Computed fields (e.g. those set in `__post_init__`) never produce prompts

## KeyPath

- **Rule:** Paths are globally unique within the normalized schema
    - *Why:* `NormalizedSchema` is a dict; collisions would silently overwrite fields

## NormalizedField

- **Rule:** `nf.type_non_aliased` is the field’s logical **user-declared** type with:
    - `Annotated` stripped
    - Optionality stripped (`T | None` → `T`)
    - container aliasing **not** applied
    - *Why:* Downstream reconstruction should use the real user type, while parsing may use alias
      shapes

---

# Session graph

**Produced in:** `_pipeline/build_session_graph.py`

The session graph is a linear, doubly-linked chain of `SessionStep` nodes. It encodes the interactive control flow:
contexts (nested schemas and schema-containers), input steps (leaf values), repeat boundaries for schema containers,
and skip targets for optional contexts.

Graph construction proceeds in phases:

base graph → expand fixed schema tuples → insert repeat exits → compute skip targets → link `prev/next`.

## Global structure

- **Rule:** The graph is a single linear chain reachable by following `.next` pointers from `SessionStart` to
  `SessionEnd`
    - *Why:* The session runner is a state machine that advances one step at a time and uses `.next` / `.prev` for
      control flow
    - *Implications:* There are no branches in `.next`; “branching” is modeled via `skip_target` and
      `RepeatExit.element_start`

- **Rule:** The first node is a `SessionStart` and the last node is a `SessionEnd`
    - *Why:* Provides a single entry/exit point for the session

- **Rule:** Every node in the chain is one of:
  `SessionStart`, `SessionEnd`, `ContextEntry`, `InputStep`, `RepeatExit`
    - *Why:* The session runner dispatches on these concrete types

- **Rule:** For every adjacent pair `(a, b)` in the chain: `a.next is b` and `b.prev is a`
    - *Why:* Undo and backtracking rely on correct bidirectional traversal

## Base graph (`_get_base_graph`)

- **Rule:** Base graph ordering follows the insertion order of the normalized schema
    - *Why:* Stable ordering ensures predictable prompt order and simplifies reasoning across pipeline phases

- **Rule:** For every `NormalizedField` in the normalized schema there is exactly one corresponding step:
    - `InputStep` if `field.shape` is one of:
      `AtomicShape`, `ContainerShape`, `DictShape`, `FixedContainerShape`, `LiteralShape`
    - otherwise `ContextEntry`
    - *Why:* Leaf-like shapes correspond to a single prompt; schema-like shapes correspond to entering a new context

- **Rule:** Every `InputStep` / `ContextEntry` has a `.parent` that is either `SessionStart` or another `ContextEntry`
    - *Why:* Parents define the current context header and are used to determine “re-entered parent context” printing

- **Rule:** Parent pointers follow the `KeyPath` prefix relation
    - *Why:* Parent-child relationships must match the schema tree
    - *Notes:* For a step with path `("a", "b", "c")`, its parent corresponds to `("a", "b")`

## Fixed schema tuples (`_expand_fixed_schema_containers`)

This phase expands contexts whose shape is `FixedSchemaContainerShape` (e.g. `tuple[T, T]`) into `N` repeated traversals
of the schema subtree.

- **Rule:** A fixed schema tuple context and all of its contiguous descendant steps are expanded together
    - *Why:* Each tuple element represents a full traversal of the same schema subtree

- **Rule:** For every clone whose original parent is inside the repeated subtree, the clone’s `.parent` points to the
  cloned parent
    - *Why:* Otherwise initialization and grouping by `(context_path, iteration)` break, and undo/header logic becomes
      incorrect

- **Rule:** Optionality of a fixed schema tuple applies only to the first repeated element
    - *Why:* `tuple[T, T] | None` means “either the whole tuple is absent, or all elements are present”
    - *Implications:* During expansion, repeats `n>0` of the tuple context must have `is_optional=False`

## Repeat exits (`_add_repeat_exits`)

This phase inserts `RepeatExit` nodes for repeatable schema containers (`SchemaContainerShape`, e.g. `list[T]` where `T`
is a schema).

- **Rule:** For each `ContextEntry` whose shape is `SchemaContainerShape`, exactly one corresponding `RepeatExit` is
  inserted

- **Rule:** A `RepeatExit` is inserted immediately before the next step that is outside the container’s subtree
    - *Why:* The decision “add another element?” must occur after finishing one element traversal and before leaving the
      container context

- **Rule:** `RepeatExit.parent` is the container `ContextEntry` it belongs to
    - *Why:* The session runner uses this association to ask “add another X?”

- **Rule:** `RepeatExit.element_start` points to the first step of the element traversal (the step immediately after the
  container context)
    - *Why:* If the user answers “yes”, control flow jumps back to the start of the next element

- **Rule:** When schema containers are nested, outer repeat exits are emitted before inner repeat exits at a shared
  boundary
    - *Why:* Prevents the session from offering to repeat an inner container after the user has already decided to leave
      the outer container
    - *Notes:* Implemented via `pending.insert(0, ...)` (“outer contexts have priority”)

## Skip targets (`_add_skips`)

This phase assigns `.skip_target` for contexts that can be skipped.

- **Rule:** Only `ContextEntry` nodes may have a `skip_target`
    - *Why:* Skipping is a context-level control flow operation

- **Rule:** For `SchemaContainerShape` contexts, `skip_target` is the step immediately after the container’s
  `RepeatExit`
    - *Why:* Answering “no” to “add this container?” must jump past the entire container traversal, **including** the
      repeat prompt

- **Rule:** For optional non-container schema contexts (`ContextEntry` where `field.is_optional`), `skip_target` is the
  step immediately after the last descendant of that context
    - *Why:* Assume no `RepeatExit` pointing to this context; if we land on a `RepeatExit` after the last descendant,
      this must be pointing to a parent context of the current one.

- **Rule:** Every `skip_target` points forward in the `.next` chain
    - *Why:* Skipping must strictly advance the session and must never re-enter the skipped context

---

# User Session

**Implemented in:** `_pipeline/run_user_session.py`

The session runner is a deterministic state machine that walks the session graph and collects user input.  
Correctness depends on a strict set of invariants about control flow, state, and undo behavior.

## Global control flow

- **Rule:** `res` is append-only except for undo operations
    - *Why:* Ensures uniform undo semantics across all contexts and container boundaries

- **Rule:** Input equal to `".."` always triggers undo, regardless of SessionStep type
    - *Why:* Uniform escape hatch across all prompts

## InputStep

- **Rule:** Each `InputStep` consumes exactly one user interaction and results in exactly one of:
    - appending a `UserInput`
    - undo
    - retrying the same step after an error

### Special input handling

- **Rule:** Empty input (`""`) is handled as follows:
    1. If the field has a default or default factory → append default value
    2. Else if `_can_skip(field)` → append `None`
    3. Else → error and retry

    - *Why:* Empty input is overloaded for defaults and optional fields; for the user, both mean 'skip this field'

- **Rule:** If parsing raises a non-`AssertionError` exception, the error is shown and the same step is retried
    - *Why:* We can't assume a specific Error type emitted from parsers, except for `AssertionError`: here we can be
      sure
      that it's library-internal
    - *Notes:* Prefer ValueError for library parsers and recommend this too the user as well for consistency
    - *Notes:* `AssertionError` may be replaced with a library-unique `CriticalError` in the future

- **Rule:** If the field uses a container alias, the parsed value is converted back to the user’s declared container
  type
    - *Why:* Aliases affect parsing only; final values must respect user-defined types

## Undo semantics

- **Rule:** Undo removes the most recent `UserInput` and resumes execution at its corresponding `InputStep`
    - *Why:* Undo is input-centric, not graph-centric

---

# Input parsing

**Implemented in:** `_pipeline/_parse_input.py`

Parsing converts raw user input strings into Python values according to an `InputShape`.
It is a pure transformation step: it does not know about session control flow, contexts, or graph structure.

## Structure parsing

- **Rule:** Structure parsing depends on the shape kind:
    - `AtomicShape`, `LiteralShape` → flat structure parsing
    - `ContainerShape`, `DictShape`, `FixedContainerShape` → nested structure parsing
    - *Why:* Only composite shapes can legally contain grouping/parentheses

### Flat structure (`_parse_structure_flat`)

- **Rule:** Flat parsing:
    - trims surrounding whitespace
    - interprets backslash escapes (`\x` → literal `x`)
    - returns a single string token
    - *Why:* Atomic and literal values should not require grouping syntax

### Nested structure (`_parse_structure_nested`)

- **Rule:** Nested parsing interprets:
    - commas as separators at the current nesting level
    - parentheses as explicit grouping
    - backslash escapes inside all contexts
    - *Why:* Composite values require a simple, uniform grammar for grouping

- **Rule:** Empty tokens are ignored (whitespace-only or empty segments between commas/parentheses)
    - *Why:* Makes input forgiving (`a, b,` behaves like `a,b`) and keeps coercion simple

- **Rule:** Nested parsing always produces a tree of `list[str | list]`
    - *Why:* Coercion relies on a uniform intermediate representation

## Parser selection

- **Rule:** For an atomic type `T`, `_select_parser(T, registry)` chooses:
    - `registry[T]` if present, otherwise
    - a fallback parser `lambda s: T(s)` (i.e. call the type constructor)
    - *Why:* Supports custom parsing while allowing sensible defaults for common types

---


