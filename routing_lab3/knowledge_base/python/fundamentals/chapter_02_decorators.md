---
topic: python
subtopic: fundamentals
chapter_id: chapter_02_decorators
document_id: py-fund
version: 1.0
---

# Decorators
A decorator is a function that wraps another function to extend or modify
its behaviour without changing its source code. The @decorator syntax is
sugar for `func = decorator(func)`. Using functools.wraps inside a
decorator preserves the wrapped function's __name__ and docstring, which
would otherwise be overwritten by the wrapper.
