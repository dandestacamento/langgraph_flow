---
topic: data_engineering
subtopic: adf
chapter_id: chapter_02_triggers
document_id: de-adf
version: 1.0
---

# ADF Triggers
ADF pipelines can be started by a schedule trigger, a tumbling window
trigger, or an event-based trigger. Tumbling window triggers uniquely
support dependency chains between consecutive time windows, re-running an
earlier window automatically if it fails.
