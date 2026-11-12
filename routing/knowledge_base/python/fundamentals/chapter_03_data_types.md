---
topic: python
subtopic: fundamentals
chapter_id: chapter_03_data_types
document_id: py-fund
version: 1.0
---

# Built-in Data Types
Core built-in types include int, float, str, and bool, plus the
container types list, tuple, dict, and set. Lists, dicts, and sets are
mutable; tuples and strings are immutable. A classic pitfall is using a
mutable object, such as a list, as a default argument value, since the
same default object is shared across every call that doesn't override it.
