---
topic: python
subtopic: concurrency
chapter_id: chapter_01_threading
document_id: py-conc
version: 1.0
---

# Threading
The threading module provides OS-level threads within a single process.
Because of the Global Interpreter Lock (GIL), CPU-bound threads do not
achieve true parallelism in standard CPython, but I/O-bound threads
benefit substantially from overlapping wait time, such as network or disk
I/O.
