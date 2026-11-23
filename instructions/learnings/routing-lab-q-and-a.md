# Routing Lab: conversations for testing

These manual tests are for the `routing_lab5` chat application. They exercise
different topics, follow-up questions, retrieval, and the knowledge-base
upload. Start the app using the [startup guide](./routing-lab-startup.md).
The app uses an LLM, so answers may vary in wording and API calls may incur
costs.

## How to use this guide

1. Select **+ New conversation** for each numbered scenario. Send its turns
   in order, waiting for each answer before sending the next.
2. Compare the answer with the expected facts; exact wording is not required.
   Record unexpected answers rather than assuming a test passed.
3. Expand **Routing details** to inspect the topic, subtopic, and retrieved
   passages. The displayed chapter is the router's selection; retrieval can
   include other chapters in the same subtopic.
4. Sources listed in an answer are retrieved sources, not proof that every
   source contributed to the answer. Open the passages to check the evidence.
5. To inspect MLflow traces, start MLflow on demand before the backend as
   described in the startup guide, then open its experiment's **Traces** tab.
   This is optional and separate from the chat's Routing details.

## 1. Uploaded dishwasher manual: specific facts

**Prerequisite:** Upload `dishwasher-manual-excerpt.pdf` through **Knowledge
base** and wait for **Indexed**. These expectations apply to the excerpt shown
in the original test; another document with the same filename may differ.

1. **Ask:** What is the duration of the Eco 50 cycle on the SmartHome DW-400 dishwasher?
   - **Expect:** 3 hours 10 minutes.
2. **Ask:** What about Intensive 70 and Quick 45?
   - **Expect:** Intensive 70 is 2 hours 5 minutes; Quick 45 is 58 minutes
     and intended for half loads. The follow-up should still refer to the DW-400.
3. **Ask:** How often should I clean its spray arms?
   - **Expect:** Monthly.

**Check:** Routing details should include the uploaded excerpt under
`appliances` / `dishwashers`; inspect its text to confirm the stated facts.
If it is missing, verify that the upload is indexed and that the backend is
using the same knowledge base. A successful upload alone does not guarantee
that every future query retrieves the document.

## 2. Dishwasher: broad question across sources

1. **Ask:** What are the features of the SmartHome DW-400 dishwasher?
   - **Expect:** An answer supported by the displayed passages. The seeded
     overview describes a 16-place-setting model, below 42 dB, with a
     two-year standard warranty and a five-year rack warranty. The uploaded
     excerpt adds cycle and maintenance information.
2. **Ask:** List the cycle names and durations in the uploaded DW-400 quick reference.
   - **Expect:** Eco 50: 3h 10m; Intensive 70: 2h 05m; Quick 45: 58 minutes,
     if the excerpt from scenario 1 is indexed and retrieved.

**Check:** A broad features answer may select only some relevant facts; it
should not be treated as a complete summary just because the upload is listed
in Sources. The seeded cycle chapter mentions an additional 1-Hour Express
cycle, while the excerpt gives a different set of named cycles. These
descriptions are not necessarily contradictory: neither establishes that its
list is exhaustive. Check for actual contradictions before assuming a source
is wrong.

Sources: [dishwasher overview](../../routing_lab5/knowledge_base/appliances/dishwashers/chapter_01_overview.md)
and [cycles](../../routing_lab5/knowledge_base/appliances/dishwashers/chapter_02_cycles.md).

## 3. Washing-machine fault and follow-up

1. **Ask:** What does error E21 mean on the SmartHome WM-500?
   - **Expect:** A drainage problem; check the pump filter and drain hose for
     blockages.
2. **Ask:** What is its standard warranty term?
   - **Expect:** Two years, referring to the WM-500.
3. **Ask:** Does that error code alone prove the repair is covered?
   - **Expect:** No. Coverage depends on the root cause and purchase date;
     do not claim a definite approval from the code alone.

**Check:** `appliances` / `washing_machines`; the relevant evidence is in
[faults](../../routing_lab5/knowledge_base/appliances/washing_machines/chapter_03_faults.md)
and [models and warranty](../../routing_lab5/knowledge_base/appliances/washing_machines/chapter_01_types.md).

**Subject-switch check:** Repeat turns 1 and 2 in the same conversation after
the DW-400 questions in scenarios 1 and 2. The warranty follow-up should
still refer to the WM-500 and route to `washing_machines`, not `dishwashers`.

## 4. Switching the model within a conversation

1. **Ask:** What is the WM-300 washing machine's capacity and standard warranty?
   - **Expect:** 7 kg and one year.
2. **Ask:** What about the WM-900 instead?
   - **Expect:** 11 kg and three years; the answer should switch models rather
     than repeat the WM-300 details.

**Check:** `appliances` / `washing_machines`;
[model details](../../routing_lab5/knowledge_base/appliances/washing_machines/chapter_01_types.md).

## 5. Refrigerator model and pronoun

1. **Ask:** Which SmartHome refrigerator has a built-in ice maker and water dispenser?
   - **Expect:** RF-700.
2. **Ask:** What is its capacity?
   - **Expect:** 700 L, referring to RF-700.

**Check:** `appliances` / `refrigerators`;
[refrigerator overview](../../routing_lab5/knowledge_base/appliances/refrigerators/chapter_01_overview.md).

## 6. Refund policy and a three-turn reference

1. **Ask:** What is SmartHome's standard refund policy for an opened large appliance returned because I changed my mind?
   - **Expect:** A 15% restocking fee. The policy's full refund within 30 days
     is for unopened, undamaged items.
2. **Ask:** What percentage is that fee?
   - **Expect:** 15%, referring to the restocking fee.
3. **Ask:** Does it still apply if the item is faulty?
   - **Expect:** No, the restocking fee does not apply when the item is faulty.

**Check:** `customer_support` / `refunds`;
[refund policy](../../routing_lab5/knowledge_base/customer_support/refunds/chapter_01_policy.md).

## 7. Order cancellation and refund timing

1. **Ask:** Can I cancel a SmartHome order before it reaches Packed status?
   - **Expect:** Yes, free of charge before it reaches Packed status.
2. **Ask:** What happens if it has already been packed?
   - **Expect:** A cancellation request is handled as a return after delivery.
3. **Ask:** After a returned item passes inspection, how long until the refund is issued?
   - **Expect:** 5 to 10 business days, to the original payment method.

**Check:** `customer_support`, with `orders` for cancellation and `refunds`
for timing. The last question deliberately changes subtopic.
Sources: [cancellation](../../routing_lab5/knowledge_base/customer_support/orders/chapter_03_cancellation.md)
and [refund process](../../routing_lab5/knowledge_base/customer_support/refunds/chapter_02_process.md).

## 8. Finance and topic switch

1. **Ask:** What is the difference between APR and APY?
   - **Expect:** APR is the stated annual rate; APY also accounts for
     compounding frequency.
2. **Ask:** How much should I keep in an emergency fund?
   - **Expect:** General guidance is three to six months of essential
     expenses in an accessible, low-risk account; it is not personalized advice.
3. **Ask:** What does washing-machine error E21 mean?
   - **Expect:** A drainage problem, not an answer about finance.

**Check:** Route the first two turns to `finance` (loans, then budgeting)
and the last to `appliances` / `washing_machines`.
Sources: [interest](../../routing_lab5/knowledge_base/finance/loans/chapter_01_interest.md)
and [emergency fund](../../routing_lab5/knowledge_base/finance/budgeting/chapter_03_emergency_fund.md).

## 9. Azure networking and follow-up

1. **Ask:** What does an Azure Network Security Group do, and how are its rules prioritized?
   - **Expect:** It filters inbound and outbound traffic using allow/deny
     rules; lower priority numbers are evaluated first.
2. **Ask:** Can it be attached to a subnet?
   - **Expect:** Yes; the follow-up should identify the NSG.

**Check:** `azure_cloud` / `networking`;
[NSGs](../../routing_lab5/knowledge_base/azure_cloud/networking/chapter_03_nsg.md)
and [subnets](../../routing_lab5/knowledge_base/azure_cloud/networking/chapter_02_subnets.md).

## 10. Python decorators

1. **Ask:** What is a Python decorator?
   - **Expect:** A function that wraps another function to extend or modify
     its behavior without changing its source code.
2. **Ask:** Why use `functools.wraps` in one?
   - **Expect:** To preserve the wrapped function's name and docstring.

**Check:** `python` / `fundamentals`;
[decorators](../../routing_lab5/knowledge_base/python/fundamentals/chapter_02_decorators.md).

## 11. Data engineering: distinct subtopics

1. **Ask:** What is a Spark partition, and what is the default shuffle partition setting?
   - **Expect:** A partition is a chunk processed by one task on one executor
     core; `spark.sql.shuffle.partitions` defaults to 200.
2. **Ask:** What capabilities does Delta Lake add to Parquet files?
   - **Expect:** ACID transactions, time travel, and schema enforcement.

**Check:** Both turns should route to `data_engineering`, but the first to
`spark` and the second to `databricks`.
Sources: [Spark partitions](../../routing_lab5/knowledge_base/data_engineering/spark/chapter_02_partitions.md)
and [Delta Lake](../../routing_lab5/knowledge_base/data_engineering/databricks/chapter_02_delta_lake.md).

## 12. Insufficient information and clarification

1. **Ask:** Is it covered?
   - **Expect:** A clarifying question instead of an invented product or
     warranty decision.
2. Start another **new conversation**. **Ask:** What is the exact delivery
   date for my order?
   - **Expect:** A request for more information or a clear statement that
     the available evidence is insufficient. The answer should not invent
     an order-specific date.

**Check:** The first question intentionally has no preceding context. Results
depend on the information and tools available in your deployment; verify
that any specific claim is supported by an actual source or tool result.

## 13. Optional: newly uploaded service advisory

**Prerequisite:** Upload [the sample DW-400 advisory](../../routing_lab5/datasets/ingestion_samples/dw-turbidity-advisory.md)
and wait for **Indexed**. If it is already indexed, reuse it rather than
uploading a duplicate.

1. **Ask:** What does error E9 mean on the SmartHome DW-400 dishwasher?
   - **Expect:** The turbidity sensor is fouled and returning implausible readings.
2. **Ask:** What should I do if it returns within three cycles?
   - **Expect:** The advisory says the sensor module, part TS-07, needs replacement.

**Check:** `appliances` / `dishwashers`; Routing details should include the
advisory. The earlier dishwasher manual excerpt is not the source of E9.

## Recording results

For each scenario, note **pass/fail**, the actual answer, and whether Routing
details included the expected evidence. For an unexpected result, distinguish
between a wrong route, missing retrieval, and an answer that omitted or
misstated retrieved evidence. If investigating later, record the conversation
and trace identifiers rather than copying API keys or sensitive messages.
