These invariants define the contracts between pipeline stages. Tests are written against these contracts; if they hold,
higher-level behavior is expected to be correct.

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

## Container alias registry

A container alias registry maps a *custom container type* to a *concrete builtin container implementation* that the
system knows how to parse (e.g. alias `MyList` → `list[str]` or `list`).

- **Rule:** The registry must be a `dict`
    - *Why:* The system expects `dict.items()` semantics

- **Rule:** Registry keys must be **concrete, non-parameterized types**
    - *Why:* Parameterized types are not stable runtime keys and are hard to reason about in user APIs
    - *Example:* `MyList[int]` as a key is invalid
    - *Example:* `MyList` as a key is valid


- **Rule:** Registry values must be concrete types or parameterized types
    - *Why:* Alias resolution inspects the value’s base type and type arguments

- **Rule:** Alias values must satisfy the same “type shape” constraints as schema fields.
    - *Why:* Alias value is used exactly as a 'normal' type hint

- **Rule:** Alias values must be subclasses of `dict`, `list`, `set`, or `tuple`
    - *Why:* The input system only knows how to parse these container families
    - *Example:* aliasing to `collections.deque` is invalid unless it subclasses one of the supported families

## Parser registry

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

- **Rule:** Every entry key is a `KeyPath` (tuple of field names) identifying a field in the schema tree
    - *Why:* Graph construction and reconstruction need a stable identifier for each field. The flat structure of a
      KeyPath makes it easier to reason about.

- **Rule:** Paths are globally unique within the normalized schema
    - *Why:* `NormalizedSchema` is a dict; collisions would silently overwrite fields

- **Rule:** The normalized schema includes entries for all fields of any nested schema reachable from the root schema
    - *Why:* Downstream stages must be able to build a complete session graph without re-inspecting user schemas

## NormalizedField

For each `NormalizedField nf`:

- **Rule:** `nf.default` and `nf.default_factory` are copied verbatim from the dataclass `Field`
    - *Why:* Defaults must behave exactly like dataclass initialization semantics

- **Rule:** `nf.annotation` is a string extracted from `typing.Annotated[...]` or empty string if absent
    - *Why:* Annotations are used purely for UX (inline hints), not for typing semantics
    - *Notes:* Annotation extraction searches through the type structure but returns at most one string value (the first
      found)

- **Rule:** `nf.is_optional` is true if the *declared field type* was optional (`T | None` / `Optional[T]`)
    - *Why:* Optionality affects session control flow (skipping contexts, marking `?`, and reconstruction behavior)

- **Rule:** `nf.type_non_aliased` `nf.type_non_aliased` is the field’s logical **user-declared** type with:
    - `Annotated` stripped
    - Optionality stripped (`T | None` → `T`)
    - container aliasing **not** applied
    - *Why:* Downstream reconstruction should use the real user type, while parsing may use alias
      shapes

## Shape kinds

Shapes describe how values are collected during the session and reconstructed afterward.
The returned shape is always one of:

- `AtomicShape(value_type)`
- `LiteralShape(values)`
- `DictShape(key: AtomicShape, value: AtomicShape)`
- `ContainerShape(container_type, element_shape)`
- `SchemaContainerShape(container_type, schema_type)`
- `FixedContainerShape(tuple_type, element_shapes)`
- `FixedSchemaContainerShape(tuple_type, schema_type, length)`
- `SchemaShape(schema_type)`

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

- **Rule:** Each cloned fixed-schema tuple context has `position_info = (n_repeat, total_repeats)`
    - *Why:* Used for UI and for distinguishing repeated traversals

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

- **Rule:** `run_user_session(step_cur, parsers, res)` dispatches solely on the concrete type of `step_cur`
  (`SessionStart`, `ContextEntry`, `InputStep`, `RepeatExit`, `SessionEnd`)
  - *Why:* The runner is a closed state machine; unexpected node types indicate a broken graph

- **Rule:** `res` is append-only except for undo operations
  - *Why:* Ensures uniform undo semantics across all contexts and container boundaries

- **Rule:** Input exactly equal to `".."` triggers undo
  - *Why:* Uniform escape hatch across all prompts

## SessionStart

- **Rule:** On `SessionStart`, the runner:
  1. prints instructions and the initial header
  2. advances unconditionally to `step_cur.next`
  - *Why:* The start node is purely presentational and never collects input
  

## ContextEntry

A context entry may be **mandatory** or **skippable**, depending on `skip_target`.

### Mandatory context

- **Rule:** If `step_cur.skip_target` is not set:
  - print the context header
  - print the annotation (if present)
  - advance to `step_cur.next`
  - *Why:* Mandatory contexts must always be traversed

### Skippable context

- **Rule:** If `step_cur.skip_target` is set, the runner prompts:
  ```
  Add <context> to <parent>? <y/n>
  ```
  - `y` → advance to `step_cur.next`
  - `n` → jump to `step_cur.skip_target`
  - `..` → undo
  - *Why:* Models optional schemas and schema containers

- **Rule:** Context annotations are printed *before* the skip prompt
  - *Why:* Annotations are intended to inform the user’s decision

- **Rule:** If `step_cur.position_info` is present, the prompt includes repeat information
  - *Why:* Required to distinguish repeated traversals of fixed schema tuples


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

- **Rule:** Non-empty input is parsed via `parse_input(v_input, field.shape, parsers)`
  - *Why:* Parsing semantics are centralized outside the session runner for readability and testabilitiy

- **Rule:** If parsing raises a non-`AssertionError` exception, the error is shown and the same step is retried
  - *Why:* Invalid user input must not crash the session

- **Rule:** If the field uses a container alias, the parsed value is converted back to the user’s declared container type
  - *Why:* Aliases affect parsing only; final values must respect user-defined types

### Context header re-printing

- **Rule:** If an `InputStep` is entered from a different parent context than the previous input, a `(contd.)` header may be printed
  - *Why:* Preserves user orientation when re-entering contexts


## RepeatExit

- **Rule:** `RepeatExit` always prompts:
  ```
  Add another <schema> to <parent>? <y/n>
  ```
  - `y` → jump to `step_cur.element_start`
  - `n` → advance to `step_cur.next`
  - `..` → undo
  - *Why:* Defines the repeat boundary for schema containers

## SessionEnd

- **Rule:** `SessionEnd` prompts:
  ```
  Finish? <y/n>
  ```
  - `y` → return the collected `SessionResult`
  - `n` → undo
  - `..` → undo
  - *Why:* Provides the opportunity to undo the final field of the schema


## Undo semantics

- **Rule:** Undo removes the most recent `UserInput` and resumes execution at its corresponding `InputStep`
  - *Why:* Undo is input-centric, not graph-centric

- **Rule:** If undo crosses a visible boundary (session end, context boundary, or repeat boundary), a context header is printed
  - *Why:* Maintains user orientation after large jumps

