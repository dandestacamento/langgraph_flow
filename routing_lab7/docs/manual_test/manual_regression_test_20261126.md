What is a Python decorator?
A decorator is a function that wraps another function to extend or modify its behaviour without changing its source code. The @decorator syntax is sugar for func = decorator(func). Using functools.wraps inside a decorator preserves the wrapped function's name and docstring, which would otherwise be overwritten by the wrapper.

Sources: chapter_01_functions, chapter_02_decorators, chapter_03_data_types

Copy
What is Method Resolution Order in Python?
Method Resolution Order (MRO) is the order in which Python looks for methods and attributes in a hierarchy of classes. When multiple inheritance is used, attribute and method lookup follows the MRO, computed using the C3 linearization algorithm.

Sources: chapter_01_classes, chapter_02_inheritance, chapter_03_dunder_methods

Copy
What is a Network Security Group used for in Azure?
A Network Security Group (NSG) filters inbound and outbound traffic to Azure resources using allow/deny rules. Rules are evaluated in priority order, where a lower priority number is evaluated first. Each rule specifies a source, destination, port range, protocol, and direction.

Sources: chapter_01_vnet, chapter_02_subnets, chapter_03_nsg

Copy
What is Delta Lake time travel?
Delta Lake is an open table format that adds ACID transactions, time travel (querying an older table version with VERSION AS OF or TIMESTAMP AS OF), and schema enforcement on top of plain Parquet files.

Sources: chapter_01_overview, chapter_02_delta_lake, chapter_03_jobs

Copy
What is the 50/30/20 budgeting rule?
A common budgeting guideline is the 50/30/20 rule: roughly 50% of after-tax income toward needs, 30% toward wants, and 20% toward savings or debt repayment, adjusted to individual circumstances.

Sources: chapter_01_basics, chapter_02_tracking, chapter_03_emergency_fund

Copy
What's the difference between APR and APY?
APR (Annual Percentage Rate) reflects the stated yearly rate, while APY (Annual Percentage Yield) also accounts for the effect of compounding frequency.

Sources: chapter_01_interest, chapter_02_amortization, chapter_03_types

Copy
What is SmartHome's refund policy for a change-of-mind return?
The standard policy allows a full refund within 30 days of delivery for unopened, undamaged items. A 15% restocking fee applies to an opened large appliance returned for a change-of-mind reason; this restocking fee does not apply when the item is faulty.

Sources: chapter_01_policy, chapter_02_process, chapter_03_exceptions

Copy
How does SmartHome organize inventory into storage partitions in its shipping warehouses?
Inventory in each regional warehouse is split across physical storage partitions by SKU category, which speeds up picking and packing.

Sources: chapter_01_shipping_methods, chapter_02_delays, chapter_03_warehouse

Copy
What's the warranty on the compressor in SmartHome refrigerators?
The compressor on every model carries an extended 10-year warranty, separate from the standard parts warranty.

Sources: chapter_01_overview, chapter_02_features, chapter_03_troubleshooting

Copy
What's the difference between a VNet and a subnet in Azure?
A Virtual Network (VNet) is an isolated network boundary within Azure, while a VNet is divided into one or more subnets, each with its own CIDR range carved out of the VNet's address space.

Sources: chapter_01_vnet, chapter_02_subnets, chapter_03_nsg

Copy
What Spark join strategy helps performance when joining a small lookup table?
Common Spark optimization techniques include using broadcast joins for small lookup tables.

Sources: chapter_01_overview, chapter_02_partitions, chapter_03_optimization

Copy
What does the spark.sql.shuffle.partitions setting default to?
The default number of partitions created after a shuffle is controlled by the spark.sql.shuffle.partitions setting, which defaults to 200.

Sources: chapter_01_overview, chapter_02_partitions, chapter_03_optimization

Copy
What are the three access tiers in Azure Blob Storage?
Azure Blob Storage stores unstructured data such as files and images in containers. Three access tiers are available: Hot, Cool, and Archive, trading off storage cost against retrieval cost and latency.

Sources: chapter_01_blob, chapter_02_table_partitions, chapter_03_redundancy

Copy
Is it covered?
Yes, the topic of Azure Blob Storage access tiers is covered in our conversation. Azure Blob Storage stores unstructured data such as files and images in containers. Three access tiers are available: Hot, Cool, and Archive, trading off storage cost against retrieval cost and latency.

Sources: chapter_01_blob, chapter_02_table_partitions, chapter_03_redundancy

Copy
What does E21 mean on the WM-500, and what is its standard warranty term?
E21 indicates a drainage problem. Check the pump filter and drain hose for blockages before assuming a pump motor failure. The WM-500 has a 2-year standard warranty.

Sources: chapter_01_types, chapter_02_operation, chapter_03_faults

Copy
My WM-500 is showing error E21 - is that covered under warranty, and what's SmartHome's standard refund policy?
The drainage problem indicated by error E21 on the WM-500 is typically covered under the standard parts warranty, as it is almost always a parts issue (related to the pump or hose) rather than a motor issue. However, coverage depends on the fault's root cause and the machine's purchase date, not solely on the error code. Therefore, it is generally covered only under the shorter standard warranty window.

Regarding SmartHome's standard refund policy, customers can receive a full refund within 30 days of delivery for unopened, undamaged items. If a large appliance is opened and returned for a change-of-mind reason, a 15% restocking fee applies; however, this fee does not apply if the item is faulty.

Sources: chapter_01_types, chapter_02_operation, chapter_03_faults, chapter_01_policy, chapter_02_process, chapter_03_exceptions

Copy
What's the price of the WM-900 washing machine?
The price of the WM-900 washing machine is $1499 AUD.

Sources: tool:sql_query

Sources: chapter_01_types, chapter_02_operation, chapter_03_faults, tool:sql_query

Copy
Which washing machine model has the largest capacity, and what's its price?
The washing machine model with the largest capacity is the WM-900, which has a capacity of 11 kg. The price of the WM-900 is $1499 AUD.

Sources: chapter_01_types, chapter_02_operation, chapter_03_faults, tool:sql_query

Copy
What is the maximum amperage draw of the RF-900 refrigerator's compressor?
Insufficient information in the knowledge base to answer this question.

Copy
Regenerate


