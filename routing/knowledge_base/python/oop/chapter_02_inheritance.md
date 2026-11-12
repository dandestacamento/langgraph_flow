---
topic: python
subtopic: oop
chapter_id: chapter_02_inheritance
document_id: py-oop
version: 1.0
---

# Inheritance
Python supports both single and multiple inheritance. When multiple
inheritance is used, attribute and method lookup follows the Method
Resolution Order (MRO), computed using the C3 linearization algorithm.
The super() function returns a proxy that follows the MRO from the
current class onward.
