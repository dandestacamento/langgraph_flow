---
topic: python
subtopic: concurrency
chapter_id: chapter_03_multiprocessing
document_id: py-conc
version: 1.0
---

# Multiprocessing
The multiprocessing module spawns separate OS processes, each with its
own Python interpreter, GIL, and memory space. This gives true parallelism
for CPU-bound work, at the cost of higher memory use and the need to
explicitly share or pickle data between processes.
