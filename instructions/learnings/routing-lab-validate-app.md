# Validating the routing-lab app

This guide explains how to run validation questions yourself in the chat UI
and, optionally, run the existing automated tests. The UI does not
automatically compare every answer with a ground-truth answer.

## 1. Prepare

1. Start `routing_lab5` using the [startup guide](./routing-lab-startup.md)
   and sign in.
2. Open the [manual Q&A scenarios](./routing-lab-q-and-a.md). Each scenario
   lists questions, expected facts, and routing or source checks.
3. If testing an upload scenario, follow its document prerequisite and wait
   until the document is **Indexed**. Do not rebuild the vector index just
   to run these tests: rebuilding can remove uploaded documents.

The app uses LLM calls, which can incur costs and produce different wording.
MLflow is optional; if you want traces, start it on demand **before the
backend** as described in the startup guide.

## 2. Test multiple questions in one conversation

This sequence tests follow-ups and topic switches in the same chat, like the
conversation in the screenshot. Start **one new conversation**, then send
the questions below one at a time in order. Compare each response with the
expected facts before continuing.

For questions 5 and 6, first upload
[the sample DW-400 service advisory](../../routing_lab5/datasets/ingestion_samples/dw-turbidity-advisory.md)
through **Knowledge base** and wait for **Indexed**. If it is already indexed,
reuse it rather than uploading it again. If it is unavailable, skip those two
questions and record them as **Blocked**.

| Turn | Question | Expected answer |
| --- | --- | --- |
| 1 | What does error E21 mean on the SmartHome WM-500? | A drainage problem; check the pump filter and drain hose for blockages. |
| 2 | What is its standard warranty term? | Two years for the WM-500. |
| 3 | Does that error code alone prove the repair is covered? | No. Coverage depends on the fault's root cause and purchase date. |
| 4 | What is the exact delivery date for my order? | Ask for more information or say the available information is insufficient; do not invent a date. |
| 5 | What does error E9 mean on the SmartHome DW-400 dishwasher? | The turbidity sensor is fouled and returning implausible readings. |
| 6 | What should I do if it returns within three cycles? | The advisory says to replace the sensor module, part TS-07. |
| 7 | What is the WM-500's standard warranty term? | Two years for the washing machine, not the dishwasher. |

**Check routing and evidence:**

- Turns 1-3 and 7 should use `appliances` / `washing_machines`. Check the
  [faults](../../routing_lab5/knowledge_base/appliances/washing_machines/chapter_03_faults.md)
  and [model warranty](../../routing_lab5/knowledge_base/appliances/washing_machines/chapter_01_types.md)
  passages.
- Turns 5-6 should use `appliances` / `dishwashers`; check that the retrieved
  passages include the uploaded advisory. Turn 6 should still refer to E9.
- Turn 4 changes the subject. Check that the answer does not carry the
  washing-machine context into the delivery question or invent an order date.

Different wording is fine when the meaning and facts agree. For example, an
answer to turn 3 need not start with "No" if it clearly says the code alone
does not determine coverage.

## 3. Run more manual scenarios

1. Select **+ New conversation** for each numbered scenario, unless its
   instructions explicitly ask you to reuse a conversation.
2. Send each question in order, waiting for the answer before the next
   question. Follow-ups such as "it" use the earlier conversation.
3. Compare the answer's meaning and important facts with **Expect**.
   The words do not have to match exactly. Check that it does not add
   unsupported claims.
4. Expand **Routing details** and compare the topic and subtopic with the
   scenario's **Check**. Inspect the retrieved passage text as well:
   listing a source alone does not prove that the answer is supported.
   The selected chapter and the retrieved chapters can differ.
5. Record **Pass**, **Fail**, or **Blocked**. Use **Blocked** if a required
   document or service is unavailable rather than counting it as a pass.

### Example: missing context

Start a **separate new conversation**, then ask **Is it covered?** Expect
a clarifying question, not an invented product or coverage decision. Asking
this in the WM-500 conversation tests a different case: the app can use the
earlier messages to interpret the question.

## 4. Record and investigate results

For each turn, record:

| Field | What to record |
| --- | --- |
| Scenario and turn | Scenario number and question |
| Result | Pass, fail, or blocked |
| Expected vs actual | Important facts expected and what the app said |
| Routing and evidence | Selected topic/subtopic and whether supporting passages were retrieved |
| Context | New conversation, or preceding turns relevant to the question |
| Details | Conversation or trace identifier and relevant error, if available |

If a result fails, check whether the question was interpreted in the right
context, whether the route was wrong, whether supporting passages were
missing, or whether the answer misstated the retrieved evidence. Do not
record API keys or sensitive messages in test notes.

## 5. Run multiple independent questions as a batch

From the repository root in PowerShell:

```powershell
cd routing_lab5
..\.venv\Scripts\python.exe scripts\run_batch_tests.py
```

The runner reads [batch test questions](../../routing_lab5/datasets/batch_test_questions.json)
and writes the expected and actual answers, routing details, and scores to
[batch_report.md](../../routing_lab5/outputs/batch_report.md). Edit the
dataset to change the questions and expected facts.

Each question runs **independently**, without conversation history, so this
does not test the follow-up sequence in section 2. Runs can incur LLM and
embedding costs. Rerunning overwrites the batch reports; manual verdicts in
`outputs\manual_review.csv` are preserved by test ID.

## 6. Optional: run automated checks

These are separate from manually asking questions in the UI. The
[routing ground truth](../../routing_lab5/datasets/routing_ground_truth.jsonl)
contains questions, expected routes and, for answer-quality cases, expected
facts. The [chat ground truth](../../routing_lab5/datasets/chat_ground_truth.jsonl)
contains conversations and expected entities for follow-up resolution.

From the repository root in PowerShell, run a focused example:

```powershell
cd routing_lab5
..\.venv\Scripts\python.exe -m pytest tests\test_rag_retrieval.py -k "L4-002" -v
```

This checks retrieval and expected answer facts for the WM-500 capacity
question. To check the subject-switch regression and existing multi-turn
condensing cases, run:

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_chat_condensing.py -k "conversation_turns_condense_correctly or product_switch or earlier_product" -v
```

Read the pytest pass/fail output; a failure includes the actual result.
These tests call the graph directly, not the chat UI, and can make billable
LLM or embedding calls. The answer metrics use text matching, with limited
equivalence for year durations (for example, "2-year" and "two years"), not
a semantic judge. Other correct paraphrases can fail a check, and matching
words alone do not prove an answer is correct. Review the answer and evidence
when a result is unclear.
