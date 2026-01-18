# Technical overview

The pipeline used in this library is: schema validation -> schema normalization -> build a session graph -> walk the graph and ask user for input -> reconstruct schema. In some respects, it's actually quite similar to how a compiler works.

## Validation

The program should crash instantly when the schema or one of the user-provided registries is invalid: when this happens 
during data input, that's poor UX (and hard to debug!) I enforce three main rules for schemas:

- Reject ambiguous types (example: `str | int` -> is the parser supposed to choose `str` or `int`?)

- Reject types that cause the end user to input nested parentheses: this causes poor UX (example: `list[list[list[str]]]` would require the user to type `((str, ...), ...)` )

- Reject types that cause the end user to lose their orientation within the graph (example: nested schemas as `dict` values)

None of the following steps should have to question the validity of schemas that get past this point.

## Normalization

This step is there so that further steps don't have to do further type introspection and don't have to refer back to the original schema, as those things are often a source of bugs. Two main goals:

- Extract relevant metadata from the original schema (defaults for example)

- Abstract the field types into shapes that are relevant to the further steps in the pipeline. Take for example a `ContainerShape`, 
which I define as "Shape representing a homogeneous container of terminal elements". The session graph further up in the pipeline does 
not care if the underlying type is `list[str]`, `set[str]` or `tuple[str, ...]`: all it needs to know is "ask the user for any number of values of type T, and don't expand into a new context".

## Build session graph

This step builds a graph that answers some of the following questions:

- Is this field a new context or an input step?

- Is this input step or context optional (ie, can I jump ahead in the graph)?

- Can the user loop back to a point earlier in the graph? (Example: after the last entry of `list[T]` where `T` is a schema)

## User session

Here we walk the graph and collect input: this is the user-facing part. The session should be able to switch solely on the shapes and graph we defined before.

The input is stored in an array of `UserInput` objects: these are simple structs that hold the input and a pointer to the matching step on the graph. I constructed it like this, so that undoing an input is as simple as popping off the last index of that array, regardless of which context that value came from. Undo functionality was very important to me: as I make quite a lot of typos myself, I'm always annoyed when I have to redo an entire form because of a typo in a previous entry!

Input validation and parsing is done in a helper module (`_parse_input`).

## Schema reconstruction

Take the original schema and the result of the session, and return an instance. 