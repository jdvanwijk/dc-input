# Technical overview

The pipeline used in this library is:

schema validation → schema normalization → session graph construction → interactive session → schema reconstruction

In some respects, it closely resembles a compiler pipeline.

---

## Validation

The program should fail fast when the schema or any user-provided registry is invalid. Discovering such errors during an interactive session results in poor UX and is difficult to debug.

Validation enforces three core constraints:

- **Reject ambiguous types**  
  Example: `str | int` — the parser cannot know which branch the user intends.

- **Reject types that force nested parentheses in user input**  
  Example: `list[list[list[str]]]` would require the user to enter `((str, ...), ...)`, which is hard to read and error-prone.

- **Reject types that cause users to lose orientation within the input graph**  
  Example: schemas nested inside dictionary values.

Schemas that pass validation are assumed to be well-formed. All downstream stages may rely on these guarantees without re-checking them.

---

## Normalization

Normalization exists so that downstream stages do not need to perform further type introspection or reference the original schema. Both are frequent sources of subtle bugs.

This step has two main goals:

- **Extract relevant metadata** from the original schema (defaults, optionality, annotations, etc.)

- **Abstract concrete Python types into a small set of structural shapes** used by later stages

For example, a `ContainerShape` represents a homogeneous container of terminal elements. At this level, it does not matter whether the original type was `list[str]`, `set[str]`, or `tuple[str, ...]`. The session graph only needs to know:

> “Ask the user for any number of values of type `T`, without introducing a new context.”

---

## Session graph construction

This stage constructs an explicit graph that encodes the interactive control flow.

The graph answers questions such as:

- Does this field introduce a new context, or is it a simple input step?
- Is this context or input optional (i.e. can it be skipped)?
- Can the user loop back to a previous point in the session?
  - Example: after entering the last element of `list[T]` where `T` is a schema

This graph is fully determined before any user interaction begins.

---

## User session

The user session walks the precomputed graph and collects input. This is the only user-facing part of the pipeline.

At this stage, behavior depends solely on:
- the session graph, and
- the normalized shapes

User input is stored as a sequence of `UserInput` records. Each record contains:
- the parsed value, and
- a reference to the corresponding node in the session graph

This design makes undo trivial: undoing an action is simply popping the last element from the input list, regardless of which context the value originated from.

Undo support is a first-class feature. Typos are common, and forcing users to restart an entire session due to a single mistake results in poor UX.

Input parsing and validation are handled by a dedicated helper module (`_parse_input`).

---

## Schema reconstruction

Finally, the original schema definition and the collected session inputs are combined to produce a fully-initialized schema instance.
