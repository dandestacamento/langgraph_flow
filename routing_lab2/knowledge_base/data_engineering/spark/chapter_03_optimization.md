---
topic: data_engineering
subtopic: spark
chapter_id: chapter_03_optimization
document_id: de-spark
version: 1.0
---

# Spark Performance Optimization
Common Spark optimization techniques include using broadcast joins for
small lookup tables, caching DataFrames that are reused across multiple
actions, avoiding unnecessary wide shuffles, and reading the Catalyst
optimizer's query plan via explain() to locate data skew.
