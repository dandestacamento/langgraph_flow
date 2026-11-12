"""Generates the controlled knowledge base used by the Routing Accuracy Lab.

Run this script once (and again whenever the content below changes) to
(re)write every Markdown chapter and supporting JSON/CSV/TXT file under
`knowledge_base/`. Keeping all the content in one data-driven script,
rather than hand-created files, makes it easy to add chapters, regenerate
everything after an edit, and keep metadata consistent.

Each chapter gets YAML front matter (topic, subtopic, chapter_id,
document_id, version) so later levels can evaluate routing down to a
specific chapter, not just a topic. Overlapping terminology is introduced
deliberately (see the "partition" note in the Spark, Azure Storage, and
Customer Support chapters below) to test whether routing/retrieval uses
context rather than keyword matching. The washing machine facts (model
WM-500, capacity, warranty, error codes E21/E42) are the ground-truth
example from instructions/Langgraph_routing/4_to_5_obserability.md.

Usage:
    python scripts/generate_knowledge_base.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "knowledge_base"

# ---------------------------------------------------------------------------
# Chapter content: topic -> subtopic -> document_id -> [(chapter_id, title, body)]
# ---------------------------------------------------------------------------

CHAPTERS: dict[str, dict[str, tuple[str, list[tuple[str, str, str]]]]] = {
    "appliances": {
        "refrigerators": ("appl-fridge", [
            ("chapter_01_overview", "Refrigerator Models and Overview", """
SmartHome Appliances sells three refrigerator lines. The RF-200 is a compact
180L model with no ice maker. The RF-450 is a standard 450L model with an
optional ice maker. The RF-700 is a 700L French-door model with a built-in
ice maker and water dispenser as standard.

All refrigerators ship with a standard 2-year parts and labour warranty.
The compressor on every model carries an extended 10-year warranty,
separate from the standard parts warranty.
"""),
            ("chapter_02_features", "Refrigerator Features", """
Common features across the refrigerator line include adjustable glass
shelves, humidity-controlled crisper drawers, and LED interior lighting.
The RF-450 and RF-700 add a digital temperature display on the door.

The RF-700 also includes a "vacation mode" that raises the internal
setpoint by 3 degrees Celsius to save energy while the home is unoccupied
for an extended period.
"""),
            ("chapter_03_troubleshooting", "Refrigerator Troubleshooting", """
Common refrigerator fault codes: E01 indicates a door-ajar sensor fault,
E05 indicates an evaporator fan failure, and E09 indicates a defrost
heater fault.

If error E05 appears, first check for ice buildup blocking the fan blade
before replacing the fan motor - ice blockages are a far more common cause
than an actual motor failure.
"""),
        ]),
        "washing_machines": ("appl-wm", [
            ("chapter_01_types", "Washing Machine Types and Models", """
SmartHome Appliances sells three washing machine models, and their capacity
and warranty terms differ significantly, so always confirm the exact model
number before answering a capacity or warranty question.

- WM-300: top-load, 7 kg capacity, 1-year standard warranty, 5-year motor warranty.
- WM-500: front-load, 9 kg capacity, 2-year standard warranty, 10-year motor warranty.
- WM-900: front-load, 11 kg capacity, smart-connect enabled, 3-year standard
  warranty, 10-year motor warranty.
"""),
            ("chapter_02_operation", "Washing Machine Operation and Cycles", """
Available wash cycles across the range include Normal, Delicate, Heavy
Duty, and Quick Wash. The WM-900 additionally offers a Steam Refresh cycle.

On the WM-500, the Quick Wash cycle completes in 30 minutes for loads under
3 kg. Heavier loads should use the Normal cycle for adequate cleaning.
"""),
            ("chapter_03_faults", "Washing Machine Fault Codes", """
These fault codes are shared across the WM-300, WM-500, and WM-900:

- E21: Drainage problem. Check the pump filter and drain hose for
  blockages before assuming a pump motor failure.
- E42: Door lock problem. Either the door is not detected as securely
  closed, or the door-locking solenoid has failed.
- E10: Water inlet fault. Check that the supply tap is open and the inlet
  filter is clean.

Whether a repair is covered under the standard parts warranty or the
extended motor warranty depends on the fault's root cause and the
machine's purchase date, not on the error code alone. A drainage fault
(E21) is almost always a parts issue (pump or hose), not a motor issue, so
it is typically covered only under the shorter standard warranty window.
"""),
        ]),
        "dishwashers": ("appl-dw", [
            ("chapter_01_overview", "Dishwasher Models", """
The dishwasher range has three models. The DW-100 is a basic 12 place
setting model with a 1-year warranty. The DW-250 is a standard 14 place
setting model with a 2-year warranty. The DW-400 is a premium 16 place
setting model, rated below 42 decibels for quiet operation, with a 2-year
standard warranty plus an additional 5-year rack warranty.
"""),
            ("chapter_02_cycles", "Dishwasher Wash Cycles", """
Standard cycles are Eco, Normal, Intensive, and Rinse-only. The DW-400
additionally offers a 1-Hour Express cycle, which requires a hot water
supply connection to achieve acceptable cleaning results in that time.
"""),
            ("chapter_03_troubleshooting", "Dishwasher Troubleshooting", """
Fault codes: E3 indicates a heating element fault, E4 indicates a water
level sensor fault, and E7 indicates a blocked drain pump.

Cloudy glassware is usually caused by hard water mineral buildup rather
than a fault code - recommend rinse aid and an occasional vinegar cycle
before troubleshooting the machine itself.
"""),
        ]),
    },
    "azure_cloud": {
        "networking": ("az-net", [
            ("chapter_01_vnet", "Virtual Networks (VNets)", """
A Virtual Network (VNet) is an isolated network boundary within Azure. Its
address space is defined using CIDR notation, for example 10.0.0.0/16.
VNets can be peered with each other to enable private connectivity between
them without routing traffic over the public internet.
"""),
            ("chapter_02_subnets", "Subnets", """
A VNet is divided into one or more subnets, each with its own CIDR range
carved out of the VNet's address space, for example 10.0.1.0/24. Azure
reserves five IP addresses in every subnet (network address, default
gateway, two for DNS, and the broadcast address). Subnets can each have
their own Network Security Group and route table attached.
"""),
            ("chapter_03_nsg", "Network Security Groups (NSGs)", """
A Network Security Group (NSG) filters inbound and outbound traffic to
Azure resources using allow/deny rules. Rules are evaluated in priority
order, where a lower priority number is evaluated first. Each rule
specifies a source, destination, port range, protocol, and direction.
"""),
        ]),
        "compute": ("az-compute", [
            ("chapter_01_vms", "Virtual Machines", """
Azure VM sizes are grouped into series: B-series are burstable and
cost-efficient for variable workloads, D-series are general purpose, and
F-series are compute-optimized. Each VM ultimately runs on a physical
host machine, which Azure refers to as a node within its underlying
cluster infrastructure.
"""),
            ("chapter_02_scale_sets", "Virtual Machine Scale Sets", """
Virtual Machine Scale Sets (VMSS) run a group of identical, load-balanced
VMs that can automatically scale out or in. Scaling rules can trigger on
CPU utilization, memory pressure, or a custom metric published to Azure
Monitor.
"""),
            ("chapter_03_app_service", "App Service", """
Azure App Service is a PaaS offering for hosting web apps and APIs. It
supports deployment slots for blue/green style releases with instant
swap-back. Compute capacity is defined by an App Service Plan, which
represents a set of compute nodes shared across every app assigned to
that plan.
"""),
        ]),
        "security": ("az-sec", [
            ("chapter_01_rbac", "Role-Based Access Control (RBAC)", """
Azure RBAC assigns roles, such as Owner, Contributor, or Reader, to a
security principal at a specific scope: a management group, subscription,
resource group, or individual resource. Role assignments are additive -
there is no explicit "deny" assignment in standard RBAC, except through
Azure Policy or the separate deny-assignment mechanism used by Blueprints.
"""),
            ("chapter_02_identity", "Managed Identity", """
A managed identity lets an Azure resource authenticate to other Azure
services without storing credentials in code or configuration. System-
assigned identities are tied to the resource's lifecycle; user-assigned
identities are standalone resources that can be shared across multiple
Azure resources.
"""),
            ("chapter_03_key_vault", "Key Vault", """
Azure Key Vault stores secrets, encryption keys, and certificates
centrally. Access can be controlled via Azure RBAC or the legacy
vault access policy model. Soft-delete and purge protection together
prevent accidental permanent loss of vault contents.
"""),
        ]),
        "storage": ("az-storage", [
            ("chapter_01_blob", "Blob Storage", """
Azure Blob Storage stores unstructured data such as files and images in
containers. Three access tiers are available: Hot, Cool, and Archive,
trading off storage cost against retrieval cost and latency.
"""),
            ("chapter_02_table_partitions", "Table Storage Partitions", """
Azure Table Storage scales by distributing rows across partitions,
identified by a PartitionKey value. Rows that share a PartitionKey are
stored together and can be queried efficiently as a batch. Choosing a
high-cardinality PartitionKey avoids a single partition becoming a
scalability hotspot under heavy load.

Note: this "partition" is a storage-layer concept used to distribute data
across storage servers. It is unrelated to a Spark DataFrame partition,
which is a unit of parallel compute, even though the two systems use the
same word.
"""),
            ("chapter_03_redundancy", "Storage Redundancy", """
Azure Storage redundancy options include LRS (locally redundant), ZRS
(zone redundant), GRS (geo-redundant), and RA-GRS (read-access
geo-redundant), trading off cost against durability and the ability to
fail over to a secondary region.
"""),
        ]),
    },
    "data_engineering": {
        "spark": ("de-spark", [
            ("chapter_01_overview", "Apache Spark Overview", """
Apache Spark is a distributed compute engine. A SparkSession is the entry
point for working with it, and DataFrames are the primary structured API,
built on top of the lower-level RDD abstraction.
"""),
            ("chapter_02_partitions", "Spark Partitions", """
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
"""),
            ("chapter_03_optimization", "Spark Performance Optimization", """
Common Spark optimization techniques include using broadcast joins for
small lookup tables, caching DataFrames that are reused across multiple
actions, avoiding unnecessary wide shuffles, and reading the Catalyst
optimizer's query plan via explain() to locate data skew.
"""),
        ]),
        "databricks": ("de-dbx", [
            ("chapter_01_overview", "Databricks Overview", """
Databricks is a managed Spark platform. Workspaces contain notebooks,
clusters, and jobs. Clusters can be all-purpose (long-running, for
interactive notebook work) or job clusters (ephemeral, created fresh for
each scheduled job run and torn down afterward).
"""),
            ("chapter_02_delta_lake", "Delta Lake", """
Delta Lake is an open table format that adds ACID transactions, time
travel (querying an older table version with VERSION AS OF or TIMESTAMP AS
OF), and schema enforcement on top of plain Parquet files.
"""),
            ("chapter_03_jobs", "Databricks Jobs", """
A Databricks Job orchestrates one or more tasks, such as notebooks, JAR
files, or Python scripts, with explicit dependencies between tasks,
configurable retries, and either a schedule or an external trigger to
start a run.
"""),
        ]),
        "adf": ("de-adf", [
            ("chapter_01_pipelines", "ADF Pipelines", """
An Azure Data Factory (ADF) pipeline groups one or more activities, such
as a Copy activity, Data Flow activity, or Stored Procedure activity, into
a single orchestrated unit that can accept parameters.
"""),
            ("chapter_02_triggers", "ADF Triggers", """
ADF pipelines can be started by a schedule trigger, a tumbling window
trigger, or an event-based trigger. Tumbling window triggers uniquely
support dependency chains between consecutive time windows, re-running an
earlier window automatically if it fails.
"""),
            ("chapter_03_data_flows", "ADF Mapping Data Flows", """
Mapping Data Flows provide a visual, Spark-backed transformation engine
inside ADF. They execute on an auto-scaling Azure Integration Runtime
cluster that ADF manages directly - they do not run inside a Databricks
workspace.
"""),
        ]),
    },
    "python": {
        "fundamentals": ("py-fund", [
            ("chapter_01_functions", "Functions", """
Python functions are defined with the def keyword. Parameters can have
default values, be passed by keyword, or be collected with *args and
**kwargs. Functions are first-class objects: they can be assigned to
variables, passed as arguments, and returned from other functions.
"""),
            ("chapter_02_decorators", "Decorators", """
A decorator is a function that wraps another function to extend or modify
its behaviour without changing its source code. The @decorator syntax is
sugar for `func = decorator(func)`. Using functools.wraps inside a
decorator preserves the wrapped function's __name__ and docstring, which
would otherwise be overwritten by the wrapper.
"""),
            ("chapter_03_data_types", "Built-in Data Types", """
Core built-in types include int, float, str, and bool, plus the
container types list, tuple, dict, and set. Lists, dicts, and sets are
mutable; tuples and strings are immutable. A classic pitfall is using a
mutable object, such as a list, as a default argument value, since the
same default object is shared across every call that doesn't override it.
"""),
        ]),
        "oop": ("py-oop", [
            ("chapter_01_classes", "Classes and Instances", """
Classes are defined with the class keyword. The __init__ method
initializes a new instance. Instance attributes are set per-object
(usually in __init__), while class attributes are shared across every
instance unless explicitly overridden.
"""),
            ("chapter_02_inheritance", "Inheritance", """
Python supports both single and multiple inheritance. When multiple
inheritance is used, attribute and method lookup follows the Method
Resolution Order (MRO), computed using the C3 linearization algorithm.
The super() function returns a proxy that follows the MRO from the
current class onward.
"""),
            ("chapter_03_dunder_methods", "Dunder Methods", """
Dunder ("double underscore") methods let custom classes integrate with
built-in syntax and protocols: __repr__ controls how an object prints,
__eq__ controls equality comparison, __len__ backs the len() function, and
__iter__ makes an object usable in a for loop.
"""),
        ]),
        "concurrency": ("py-conc", [
            ("chapter_01_threading", "Threading", """
The threading module provides OS-level threads within a single process.
Because of the Global Interpreter Lock (GIL), CPU-bound threads do not
achieve true parallelism in standard CPython, but I/O-bound threads
benefit substantially from overlapping wait time, such as network or disk
I/O.
"""),
            ("chapter_02_asyncio", "Asyncio", """
Asyncio provides async/await syntax and a single-threaded event loop for
cooperative multitasking. It is well suited to high-concurrency,
I/O-bound workloads, such as handling many simultaneous network
connections, without the overhead of one OS thread per connection.
"""),
            ("chapter_03_multiprocessing", "Multiprocessing", """
The multiprocessing module spawns separate OS processes, each with its
own Python interpreter, GIL, and memory space. This gives true parallelism
for CPU-bound work, at the cost of higher memory use and the need to
explicitly share or pickle data between processes.
"""),
        ]),
    },
    "finance": {
        "budgeting": ("fin-budget", [
            ("chapter_01_basics", "Budgeting Basics", """
A common budgeting guideline is the 50/30/20 rule: roughly 50% of
after-tax income toward needs, 30% toward wants, and 20% toward savings or
debt repayment, adjusted to individual circumstances.
"""),
            ("chapter_02_tracking", "Expense Tracking", """
Common expense-tracking approaches include zero-based budgeting (every
dollar of income is assigned a job before the month starts), the envelope
system (cash or virtual "envelopes" per category), and dedicated tracking
apps that categorize transactions automatically.
"""),
            ("chapter_03_emergency_fund", "Emergency Funds", """
General guidance suggests keeping three to six months of essential
expenses in an easily accessible, low-risk account as an emergency fund,
separate from longer-term investments.
"""),
        ]),
        "loans": ("fin-loans", [
            ("chapter_01_interest", "Interest Basics", """
Simple interest is calculated only on the original principal. Compound
interest is calculated on the principal plus any interest already
accrued. APR (Annual Percentage Rate) reflects the stated yearly rate,
while APY (Annual Percentage Yield) also accounts for the effect of
compounding frequency.
"""),
            ("chapter_02_amortization", "Amortization", """
An amortization schedule splits each fixed payment on a loan into an
interest portion and a principal portion. On a standard amortizing loan,
early payments are interest-heavy, with the principal portion of each
payment growing over the life of the loan.
"""),
            ("chapter_03_types", "Loan Types", """
Common loan structures include fixed-rate (constant rate for the loan
term), variable-rate (rate moves with a reference rate), interest-only
(no principal repayment for an initial period), and balloon loans (a
large final payment due at the end of the term).
"""),
        ]),
        "investments": ("fin-invest", [
            ("chapter_01_returns", "Investment Returns", """
Nominal return is the raw percentage gain on an investment. Real return
adjusts the nominal return for inflation. CAGR (Compound Annual Growth
Rate) expresses the smoothed annual growth rate that would produce the
same overall return across multiple years.
"""),
            ("chapter_02_risk", "Risk and Volatility", """
Standard deviation of returns is commonly used as a proxy for an
investment's volatility. An appropriate level of risk depends on both
risk tolerance and investment time horizon, not on volatility alone.
"""),
            ("chapter_03_diversification", "Diversification", """
Diversification spreads investments across different asset classes and
sectors to reduce unsystematic (asset-specific) risk. The correlation
between holdings matters more for risk reduction than simply the raw
number of different holdings.
"""),
        ]),
    },
    "customer_support": {
        "orders": ("cs-orders", [
            ("chapter_01_placing", "Placing an Order", """
The standard order flow is: add items to cart, proceed to checkout,
authorize payment, then receive a confirmation email containing the order
number, formatted as ORD- followed by six digits (for example ORD-004821).
"""),
            ("chapter_02_tracking", "Order Tracking", """
Orders move through these statuses: Processing, Packed, Shipped, Out for
Delivery, and Delivered. Carrier tracking updates can lag the physical
movement of the parcel by up to 24 hours, which is normal and does not by
itself indicate a delivery problem.
"""),
            ("chapter_03_cancellation", "Order Cancellation", """
An order can be cancelled free of charge any time before it reaches the
Packed status. Once an order has been packed, a cancellation request is
instead handled as a return once the item has been delivered.
"""),
        ]),
        "refunds": ("cs-refunds", [
            ("chapter_01_policy", "Refund Policy", """
The standard policy allows a full refund within 30 days of delivery for
unopened, undamaged items. A 15% restocking fee applies to an opened large
appliance returned for a change-of-mind reason; this restocking fee does
not apply when the item is faulty.
"""),
            ("chapter_02_process", "Refund Process", """
Once a returned item passes warehouse inspection, the refund is issued to
the original payment method within 5 to 10 business days.
"""),
            ("chapter_03_exceptions", "Refund Exceptions", """
Final-sale and clearance items are not eligible for a change-of-mind
refund, but they remain covered by standard statutory faulty-goods
protections regardless of their final-sale status.
"""),
        ]),
        "delivery": ("cs-delivery", [
            ("chapter_01_shipping_methods", "Shipping Methods", """
Available shipping methods are Standard (3 to 7 business days), Express
(1 to 2 business days), and White Glove delivery for large appliances,
which includes installation and removal of the old unit.
"""),
            ("chapter_02_delays", "Delivery Delays", """
Common causes of delivery delays include carrier network congestion, an
incorrect delivery address, and failed delivery attempts. A redelivery fee
may apply after two failed delivery attempts at the customer's address.
"""),
            ("chapter_03_warehouse", "Warehouse Operations", """
Inventory in each regional warehouse is split across physical storage
partitions by SKU category, which speeds up picking and packing.

Note: this "partition" refers to a physical storage zone in a warehouse.
It is unrelated to a Spark compute partition or an Azure Table Storage
partition, even though the two systems use the same word.
"""),
        ]),
    },
}

FRONT_MATTER_TEMPLATE = """---
topic: {topic}
subtopic: {subtopic}
chapter_id: {chapter_id}
document_id: {document_id}
version: 1.0
---

# {title}
{body}"""


def write_chapters() -> int:
    count = 0
    for topic, subtopics in CHAPTERS.items():
        for subtopic, (document_id, chapters) in subtopics.items():
            out_dir = KB / topic / subtopic
            out_dir.mkdir(parents=True, exist_ok=True)
            for chapter_id, title, body in chapters:
                content = FRONT_MATTER_TEMPLATE.format(
                    topic=topic,
                    subtopic=subtopic,
                    chapter_id=chapter_id,
                    document_id=document_id,
                    title=title,
                    body=body.strip() + "\n",
                )
                (out_dir / f"{chapter_id}.md").write_text(content, encoding="utf-8")
                count += 1
    return count


# ---------------------------------------------------------------------------
# Supporting structured documents (CSV / JSON / TXT) referenced by chapters
# ---------------------------------------------------------------------------

def write_supporting_documents() -> list[Path]:
    written: list[Path] = []

    wm_csv = KB / "appliances" / "washing_machines" / "specifications.csv"
    with wm_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "type", "capacity_kg", "standard_warranty_years", "motor_warranty_years", "price_aud"])
        writer.writerow(["WM-300", "top-load", 7, 1, 5, 699])
        writer.writerow(["WM-500", "front-load", 9, 2, 10, 999])
        writer.writerow(["WM-900", "front-load", 11, 3, 10, 1499])
    written.append(wm_csv)

    fridge_csv = KB / "appliances" / "refrigerators" / "specifications.csv"
    with fridge_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "type", "capacity_l", "standard_warranty_years", "compressor_warranty_years", "price_aud"])
        writer.writerow(["RF-200", "compact", 180, 2, 10, 599])
        writer.writerow(["RF-450", "standard", 450, 2, 10, 999])
        writer.writerow(["RF-700", "french-door", 700, 2, 10, 1799])
    written.append(fridge_csv)

    spark_json = KB / "data_engineering" / "spark" / "spark_config.json"
    spark_json.write_text(
        json.dumps(
            {
                "spark.sql.shuffle.partitions": 200,
                "spark.sql.adaptive.enabled": True,
                "spark.sql.adaptive.coalescePartitions.enabled": True,
                "notes": "Default shuffle partition count; tune down for small clusters/datasets.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    written.append(spark_json)

    loan_csv = KB / "finance" / "loans" / "loan_rates.csv"
    with loan_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["loan_type", "typical_apr_low", "typical_apr_high"])
        writer.writerow(["fixed-rate mortgage", 5.5, 7.0])
        writer.writerow(["variable-rate mortgage", 5.0, 7.5])
        writer.writerow(["personal loan", 7.0, 15.0])
        writer.writerow(["car loan", 6.0, 12.0])
    written.append(loan_csv)

    policies_txt = KB / "customer_support" / "general_policies.txt"
    policies_txt.write_text(
        "SmartHome Appliances - General Customer Support Policy Summary\n"
        "================================================================\n\n"
        "- Standard refund window: 30 days from delivery.\n"
        "- Orders can be cancelled free of charge before the Packed status.\n"
        "- White Glove delivery is available for all large appliances.\n"
        "- Final-sale/clearance items keep statutory faulty-goods rights.\n"
        "- This file is a plain-text summary; see the refunds/, orders/, and\n"
        "  delivery/ chapters for authoritative detail.\n",
        encoding="utf-8",
    )
    written.append(policies_txt)

    return written


def main() -> None:
    n_chapters = write_chapters()
    extra = write_supporting_documents()
    print(f"Wrote {n_chapters} Markdown chapters under {KB}")
    print(f"Wrote {len(extra)} supporting documents:")
    for path in extra:
        print(f"  - {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
