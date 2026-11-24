---
topic: azure_cloud
subtopic: storage
chapter_id: chapter_02_table_partitions
document_id: az-storage
version: 1.0
---

# Table Storage Partitions
Azure Table Storage scales by distributing rows across partitions,
identified by a PartitionKey value. Rows that share a PartitionKey are
stored together and can be queried efficiently as a batch. Choosing a
high-cardinality PartitionKey avoids a single partition becoming a
scalability hotspot under heavy load.

Note: this "partition" is a storage-layer concept used to distribute data
across storage servers. It is unrelated to a Spark DataFrame partition,
which is a unit of parallel compute, even though the two systems use the
same word.
