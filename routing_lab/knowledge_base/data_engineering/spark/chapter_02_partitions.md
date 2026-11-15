---
topic: data_engineering
subtopic: spark
chapter_id: chapter_02_partitions
document_id: de-spark
version: 1.0
---

# Spark Partitions
A Spark partition is a chunk of a DataFrame or RDD that is processed by a
single task on a single executor core. The default number of partitions
created after a shuffle is controlled by the spark.sql.shuffle.partitions
setting, which defaults to 200. Too few partitions underutilizes the
cluster; too many adds scheduling overhead that can outweigh the benefit
of parallelism.

Note: this "partition" is a unit of parallel compute within a single
Spark job. It is unrelated to an Azure Table Storage partition or a
physical warehouse storage partition, even though the two systems use the
same word.
