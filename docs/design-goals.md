# Design goals

These goals guide design decisions and inform invariants. They are not expected to be mechanically testable, and may
be partially or indirectly enforced through invariants.

- **Goal:** Session result should be deterministic
    - *Why:* We don't want any 'magic' for the library user: because the library user depends on correctness, the
      library
      should be as transparent and predictable as possible

- **Goal:** End users should never have to write nested parentheses
    - *Why:* Would result in poor UX, we can't assume that the end user is a programmer

- **Goal:** End users should never feel disoriented within the input graph
    - *Why:* The library’s UX depends on maintaining orientation across nested structures

- **Goal:** The system should treat subclasses of supported builtin types as compatible with their base types.
    - *Why:* Easier integration with existing user schemas, more inviting to users writing OOP code
    - *Implications:* Never switch on `T is U`; always check whether `T` is a subclass of `U`
    - *Notes:* Use `alt_issubclass` from `_pipeline/_utils.py` for subclass checks

- **Goal:** Prefer the smallest feature set that solves real user problems
    - *Why:* Stabilize core behavior and reduce bug surface area
    - *Implications:* Only add features when there’s demonstrated demand (issues, discussions, repeated questions)

- **Goal:** Keep the library single-purpose: schema → interactive session → initialized schema instance
    - *Why:* Clarity, maintainability, and a coherent mental model for users
    - *Implications:* Export/serialization helpers (YAML/JSON/etc.) stay out of scope unless they directly support the
      core flow

- **Goal:** Extract core from dc-input library and make adapters for `attrs` and `pydantic`
    - *Why:* Both libraries provide the user with advanced validation, which lines up with our design goals (
      correctness)
    - *Implications:* Prevent excessive coupling in `dc-input` to make core extraction easier