# Lab 7: manual regression questions and answers

Use this guide to test the app yourself in the chat UI. The answers are
reference expectations, not proof that the app is accurate. The SmartHome
products, prices and policies are **fictional test data**, not real product
or financial advice.

## Preparation

1. Start lab 7 using the [startup guide](../../instructions/learnings/routing-lab-startup.md)
   and open `http://localhost:5173`.
2. The general questions use the lab 7 curated knowledge base. For NIST
   questions, upload `NIST.AI.100-1.pdf` to **Knowledge base**, approve its
   classification if required, and wait for **Indexed**. These expectations
   refer to *NIST AI 100-1, AI RMF 1.0*; check the version in the app.
3. For DW-650 questions, upload
   [dishwasher_manual_file2.pdf](../../instructions/sample_files/dishwasher_manual_file2.pdf)
   to **Knowledge base**, approve classification if required, and wait for
   **Indexed**. This is a fictional sample; it is not the DW-400 excerpt.
4. Record the date, app/commit version, document versions and whether the
   response cache is enabled. For fresh model responses, set
   `ROUTING_LAB_CACHE_ENABLED=0` **before starting the backend**. This can
   increase model calls and cost. Restart the backend after code changes;
   specialist answer checks and multi-topic synthesis checks also add model
   calls, latency and cost. These checks are fallible. Optional MLflow tracing
   is on demand only.

## How to test

- Start a **new conversation for each question** in sections 1-3. For section
  4, start a new conversation for each scenario and send its questions in
  order. This prevents earlier messages from changing standalone questions.
- Compare the answer's meaning with the expectation, not its exact wording.
  Expand **Routing details** and open the retrieved passages. Check whether
  they actually support every material claim, whether details are missing or
  invented, and whether uncertainty is stated when evidence is insufficient.
  A source list is a list of retrieved references, not verified citations.
- Mark **Pass** only if the answer and supporting evidence are adequate;
  mark **Fail** for an incorrect or unsupported claim, and **Blocked** when a
  required document, service or answer is unavailable. Record route and
  follow-up problems as well as answer problems. Do not equate an automated
  substring match with a correct answer.
- Keep your results in your own notes, or enter verdicts and comments against
  matching IDs in the existing
  [general manual review CSV](../outputs/manual_review.csv). That CSV covers
  general batch IDs; use separate notes for the other sections. The chat UI
  does **not** fill this file automatically. Do not overwrite an existing
  report or another person's notes.

Suggested record for each case: `ID | date | Pass/Fail/Blocked | actual answer
or summary | supporting source/page | route | notes`. Avoid recording sensitive
content in shared files.

## 1. General knowledge and routing

Use the [general dataset](../datasets/batch_test_questions.json) for the full
reference answers. The linked curated sources below are the starting point for
review; an uploaded document may add or conflict with evidence.

| ID | Ask | Expected result and source |
| --- | --- | --- |
| T001 | What is a Python decorator? | A function that wraps another function to extend or modify its behavior. `functools.wraps` preserves metadata. [Decorators](../knowledge_base/python/fundamentals/chapter_02_decorators.md). |
| T002 | What is Method Resolution Order in Python? | The order used to look up methods and attributes with inheritance; Python uses C3 linearization. [Inheritance](../knowledge_base/python/oop/chapter_02_inheritance.md). |
| T003 | What is a Network Security Group used for in Azure? | It filters inbound and outbound traffic using allow/deny rules; lower priority numbers are evaluated first. [NSGs](../knowledge_base/azure_cloud/networking/chapter_03_nsg.md). |
| T004 | What is a PartitionKey used for in Azure Table Storage? | It groups rows into partitions; a high-cardinality key can help spread load, but does not prevent hotspots when requests concentrate on one key. [Table partitions](../knowledge_base/azure_cloud/storage/chapter_02_table_partitions.md). |
| T005 | What is Delta Lake time travel? | Query an earlier version of a table, for example with `VERSION AS OF` or `TIMESTAMP AS OF`. [Delta Lake](../knowledge_base/data_engineering/databricks/chapter_02_delta_lake.md). |
| T006 | What is the 50/30/20 budgeting rule? | Roughly 50% of after-tax income for needs, 30% for wants and 20% for savings or debt repayment. [Budgeting](../knowledge_base/finance/budgeting/chapter_01_basics.md). |
| T007 | What's the difference between APR and APY? | APR is the stated annual rate; APY also accounts for compounding frequency. [Interest](../knowledge_base/finance/loans/chapter_01_interest.md). |
| T008 | What is SmartHome's refund policy for a change-of-mind return? | Full refund within 30 days for unopened, undamaged items; a 15% restocking fee applies to an opened large appliance for change of mind, not a faulty item. [Refund policy](../knowledge_base/customer_support/refunds/chapter_01_policy.md). |
| T009 | How does SmartHome organize inventory into storage partitions in its shipping warehouses? | By SKU category in physical warehouse zones; not Spark or Azure partitions. [Warehouse](../knowledge_base/customer_support/delivery/chapter_03_warehouse.md). |
| T010 | What's the warranty on the compressor in SmartHome refrigerators? | A 10-year compressor warranty, separate from the 2-year parts and labour warranty. [Refrigerator overview](../knowledge_base/appliances/refrigerators/chapter_01_overview.md). |
| T011 | What's the difference between a VNet and a subnet in Azure? | A VNet is an isolated network with an address space; a subnet is a smaller range within that VNet. [VNet](../knowledge_base/azure_cloud/networking/chapter_01_vnet.md), [subnets](../knowledge_base/azure_cloud/networking/chapter_02_subnets.md). |
| T012 | What Spark join strategy helps performance when joining a small lookup table? | A broadcast join. The cited chapter recommends it but does not explain its mechanism. [Spark optimization](../knowledge_base/data_engineering/spark/chapter_03_optimization.md). |
| T013 | What does the spark.sql.shuffle.partitions setting default to? | 200, according to this test knowledge base. [Spark partitions](../knowledge_base/data_engineering/spark/chapter_02_partitions.md). |
| T014 | What are the three access tiers in Azure Blob Storage? | Hot, Cool and Archive, according to this test knowledge base. [Blob storage](../knowledge_base/azure_cloud/storage/chapter_01_blob.md). |
| T015 | Is it covered? | Ask what item or service is meant; do not assume a referent. Run this in a fresh conversation. |
| T016 | What does E21 mean on the WM-500, and what is its standard warranty term? | E21 is a drainage fault; WM-500 has a 2-year standard warranty. The term alone does not establish coverage of a specific repair. [Faults](../knowledge_base/appliances/washing_machines/chapter_03_faults.md), [models](../knowledge_base/appliances/washing_machines/chapter_01_types.md). |
| T017 | My WM-500 is showing error E21 - is that covered under warranty, and what's SmartHome's standard refund policy? | E21 is a drainage fault; specific coverage depends on root cause and purchase date. The standard refund is within 30 days for unopened, undamaged items. [Faults](../knowledge_base/appliances/washing_machines/chapter_03_faults.md), [refund policy](../knowledge_base/customer_support/refunds/chapter_01_policy.md). |
| T018 | What's the price of the WM-900 washing machine? | AUD 1,499 according to the test specifications; inspect the `sql_query` tool result. [Specifications](../knowledge_base/appliances/washing_machines/specifications.csv). |
| T019 | Which washing machine model has the largest capacity, and what's its price? | WM-900, 11 kg, AUD 1,499. Inspect the multi-hop results and evidence for both facts. [Models](../knowledge_base/appliances/washing_machines/chapter_01_types.md), [specifications](../knowledge_base/appliances/washing_machines/specifications.csv). |
| T020 | What is the maximum amperage draw of the RF-900 refrigerator's compressor? | With the curated knowledge base alone, there is insufficient information. Do not invent an amperage or claim a model does not exist outside the available sources. [Refrigerator overview](../knowledge_base/appliances/refrigerators/chapter_01_overview.md). |

For the T015/T017/T018 improvements, retest those three cases in separate new
conversations, plus a valid contextual warranty follow-up from section 4.
For T018, expect one application-generated `Sources:` line, including
`tool:sql_query` when the SQL tool was used. For T017, a refusal to verify
an otherwise supported answer is also a regression; record it for review.

**T004 and T017:** The dataset references and curated sources were corrected
after review. The automated fact-substring score can still pass an answer
that overstates hotspot avoidance or warranty coverage; inspect the full
answer and supporting evidence.

## 2. NIST AI RMF questions

Reference: [NIST AI RMF 1.0](https://doi.org/10.6028/NIST.AI.100-1),
the indexed copy in the app, and the [NIST dataset](../datasets/nist_questions.json).
Compare against the actual PDF passage, not only this short summary. Expected
topic/subtopic in the dataset is `artificial_intelligence` / `risk_management`;
the approved classification in your installation may differ.

| ID | Ask | Expected result |
| --- | --- | --- |
| NIST-01 | What two outcomes does the AI RMF aim for when addressing AI impacts? | Minimize negative impacts and identify opportunities to maximize positive impacts. |
| NIST-02 | What are the four AI RMF Core functions? | GOVERN, MAP, MEASURE and MANAGE. |
| NIST-03 | Assuming a governance structure is in place, must the AI RMF functions be performed in a fixed order? | No; they may be performed in an order appropriate to the user. |
| NIST-04 | Which three functions is GOVERN designed to be infused throughout? | MAP, MEASURE and MANAGE. |
| NIST-05 | The outcomes of MAP form the basis for which two functions? | MEASURE and MANAGE. |
| NIST-06 | According to the MEASURE function, when should AI systems be tested? | Before deployment and regularly during operation. |
| NIST-07 | What four risk-response options are listed in MANAGE 1.3? | Mitigate, transfer, avoid and accept risk. |
| NIST-08 | According to MANAGE 4.3, to whom should incidents and errors be communicated? | Relevant AI actors, including affected communities. |
| NIST-09 | Does the AI RMF prescribe an organization's risk tolerance? | No. |
| NIST-10 | What seven characteristics of trustworthy AI are listed in the framework? | Valid and reliable; safe; secure and resilient; accountable and transparent; explainable and interpretable; privacy-enhanced; fair with harmful bias managed. |
| NIST-11 | Which questions do transparency, explainability, and interpretability respectively help answer? | Transparency: what happened; explainability: how a decision was made; interpretability: why it was made and its meaning or context. |
| NIST-12 | What three major categories of AI bias does NIST identify? | Systemic, computational and statistical, and human-cognitive bias. |
| NIST-13 | An AI RMF use-case profile is based on which three aspects of the framework user? | Requirements, risk tolerance and resources. |
| NIST-14 | What is the difference between an AI RMF Current Profile and a Target Profile? | A Current Profile describes current outcomes; a Target Profile describes outcomes needed for desired goals. |
| NIST-15 | What should be employed when choosing trustworthiness metrics and their precise threshold values? | Human judgment. The relevant passage is on PDF page 17 of the 48-page AI RMF 1.0 file. |

## 3. DW-650 uploaded manual questions

Reference: [fictional DW-650 manual](../../instructions/sample_files/dishwasher_manual_file2.pdf)
and [dishwasher dataset](../datasets/dishwasher_manual_file2_questions.json).
Page numbers below refer to that six-page PDF, not a different manual.

| ID | Ask | Expected result | PDF page |
| --- | --- | --- | --- |
| DW650-01 | How many place settings does the SmartHome DW-650 dishwasher hold? | 14 place settings. | 1 |
| DW650-02 | What does CL mean on the SmartHome DW-650 dishwasher display? | The child lock is active. | 1 |
| DW650-03 | How many minutes does the SmartHome DW-650 dishwasher Eco 50 cycle take? | 185 minutes. | 2 |
| DW650-04 | Which SmartHome DW-650 dishwasher cycle uses a 70 C final rinse? | Hygiene 70. | 2 |
| DW650-05 | Where should tall plates be placed in the SmartHome DW-650 dishwasher? | In the lower rack. | 3 |
| DW650-06 | Which SmartHome DW-650 dishwasher part should be cleaned every 14 days? | The removable mesh filter. | 4 |
| DW650-07 | What does error E14 mean on the SmartHome DW-650 dishwasher? | Low incoming water flow. | 5 |
| DW650-08 | What does error E26 mean on the SmartHome DW-650 dishwasher? | A restricted drain path. | 5 |
| DW650-09 | What does error E33 mean on the SmartHome DW-650 dishwasher? | The door latch was not detected as closed. | 5 |
| DW650-10 | What is the standard warranty term for the SmartHome DW-650 dishwasher? | 3 years. | 6 |
| DW650-11 | What is the motor warranty term for the SmartHome DW-650 dishwasher? | 7 years. | 6 |
| DW650-12 | What information should I provide when contacting support about the SmartHome DW-650 dishwasher? | Model number, serial number and purchase date. | 6 |

## 4. Multi-turn chat scenarios

For each scenario, start one new conversation and ask the turns in order.
The [chat dataset](../datasets/chat_ground_truth.jsonl) also contains
follow-up and topic-switch cases.

### M01: fault and follow-up

1. **Ask:** What does error E21 mean on the SmartHome WM-500?
   **Expect:** A drainage problem.
2. **Ask:** What is its standard warranty term?
   **Expect:** Two years, referring to the WM-500.
3. **Ask:** Does that error code alone prove the repair is covered?
   **Expect:** No; the fault's root cause and purchase date matter.

Sources: [faults](../knowledge_base/appliances/washing_machines/chapter_03_faults.md),
[models](../knowledge_base/appliances/washing_machines/chapter_01_types.md).

### M02: switch models

1. **Ask:** What is the WM-300 washing machine's capacity and standard warranty?
   **Expect:** 7 kg and one year.
2. **Ask:** What about the WM-900 instead?
   **Expect:** 11 kg and three years, not the WM-300's details.

Source: [washing-machine models](../knowledge_base/appliances/washing_machines/chapter_01_types.md).

### M03: refund and pronouns

1. **Ask:** What is SmartHome's standard refund policy for an opened large appliance returned because I changed my mind?
   **Expect:** A 15% restocking fee.
2. **Ask:** What percentage is that fee?
   **Expect:** 15%, referring to the restocking fee.
3. **Ask:** Does it still apply if the item is faulty?
   **Expect:** No, the restocking fee does not apply when the item is faulty.

Source: [refund policy](../knowledge_base/customer_support/refunds/chapter_01_policy.md).

## 5. Report results

Share failed or blocked case IDs, the actual answer, the relevant source/page,
and any routing details so the issue can be investigated. Distinguish an
incorrect expectation or missing document from a model failure. Re-run the
affected cases manually after a fix and retain the earlier results for
comparison. Do not include private documents or credentials in shared reports.
