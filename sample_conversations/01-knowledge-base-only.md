# Sample conversation 1 - knowledge base only (no uploads)

Click **+ New conversation** first. Each block shows what to type and what to expect.

---

### Turn 1 - simple fault lookup (or click the matching starter chip)

> **You:** What does refrigerator error code E05 indicate?

**Expected:** "E05 indicates an evaporator fan failure." with sources. Routing details shows
`appliances › refrigerators › chapter_03_troubleshooting`, an execution timeline
(check_input → condense → invoke_routing_pipeline → check_output → record_turn with timings),
and clickable passage cards. The sidebar title becomes something like
*"Refrigerator error code E05 explanation"*.

### Turn 2 - multi-hop with a tool call

> **You:** Which refrigerator model has the largest capacity, and what's its price?

**Expected:** "…the RF-700, which has a capacity of 700L… The price of the RF-700 is
$1799 AUD." Routing details shows a **two-hop trace**: Hop 1 identifies RF-700
(`Extracted: RF-700`), Hop 2 fetches the price via a `sql_query` tool call.

### Turn 3 - follow-up resolved from conversation memory

> **You:** Is that fridge covered by the compressor warranty?

**Expected:** "that fridge" resolves to the RF-700 from turn 2 - the answer covers the
standard 2-year parts warranty and the separate 10-year compressor warranty, with
refrigerator chapter citations.

### Turn 4 - topic switch (customer support)

> **You:** Does the 15% restocking fee apply to a faulty large appliance return?

**Expected:** "This restocking fee does not apply when the item is faulty." Routing details
now shows `customer_support › refunds › chapter_01_policy` - a completely different branch.

### Turn 5 - conversation-meta question (answered from memory, not RAG)

> **You:** What was my previous question?

**Expected:** It names turn 4's question. **No Routing details panel** - this is answered
from conversation memory; nothing was routed or retrieved.

### Turn 6 - conversation summary

> **You:** Summarize our conversation.

**Expected:** An accurate recap of turns 1-5, again with no Routing details.

### Things to try on any answer

- **Copy** / **Regenerate** buttons appear on hover of the last answer.
- Press **F5**: every turn, citation, and the generated title restore from the server.
- Ask something the knowledge base can't answer (e.g. *"Who won the 2022 World Cup?"*):
  expected answer is a refusal - *"Insufficient information in the knowledge base to answer
  this question."* - never a guess. That is the anti-hallucination guardrail, not a bug.
