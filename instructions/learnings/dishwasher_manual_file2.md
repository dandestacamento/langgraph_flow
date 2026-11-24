# DW-650 sample manual: upload and validation

The [six-chapter sample PDF](../sample_files/dishwasher_manual_file2.pdf)
is **fictional test data**, not instructions or warranty terms for a real
dishwasher. It covers controls, cycles, loading, care, faults, and warranty.
These tests use `routing_lab5`.

## 1. Upload the PDF manually

1. Start the app using the [startup guide](./routing-lab-startup.md). If
   the backend was already running before the latest code changes, restart
   it so multi-page PDFs are split into retrievable page chunks.
2. Sign in, select **Knowledge base**, and upload
   `instructions\sample_files\dishwasher_manual_file2.pdf`.
3. Wait until its status is **Indexed**. Check that the classification is
   `appliances` / `dishwashers` and that the pipeline shows multiple chunks.
   If it needs review, use the Knowledge Base Manager's classification
   override; if it fails, inspect the pipeline log before continuing.
4. If this exact PDF is already indexed, reuse it rather than uploading a
   duplicate. Uploads are stored under `routing_lab5\data\documents` and
   indexed in `routing_lab5\.chroma`; they are not added as files under
   `knowledge_base\appliances\dishwashers`.

Do not rebuild the Chroma index just for this test: rebuilding can remove
uploaded documents. The backend and batch command must use the same
`routing_lab5` index.

## 2. Test the questions manually

Open a **new conversation** and ask the following questions in order.
The questions name the model so they can also be tested independently.
Compare meaning, not exact wording.

| ID | Question | Expected answer |
| --- | --- | --- |
| DW650-01 | How many place settings does the SmartHome DW-650 dishwasher hold? | 14 place settings. |
| DW650-02 | What does CL mean on the SmartHome DW-650 dishwasher display? | The child lock is active. |
| DW650-03 | How many minutes does the SmartHome DW-650 dishwasher Eco 50 cycle take? | 185 minutes. |
| DW650-04 | Which SmartHome DW-650 dishwasher cycle uses a 70 C final rinse? | Hygiene 70. |
| DW650-05 | Where should tall plates be placed in the SmartHome DW-650 dishwasher? | In the lower rack. |
| DW650-06 | Which SmartHome DW-650 dishwasher part should be cleaned every 14 days? | The removable mesh filter. |
| DW650-07 | What does error E14 mean on the SmartHome DW-650 dishwasher? | Low incoming water flow. |
| DW650-08 | What does error E26 mean on the SmartHome DW-650 dishwasher? | A restricted drain path. |
| DW650-09 | What does error E33 mean on the SmartHome DW-650 dishwasher? | The door latch was not detected as closed. |
| DW650-10 | What is the standard warranty term for the SmartHome DW-650 dishwasher? | Three years. |
| DW650-11 | What is the motor warranty term for the SmartHome DW-650 dishwasher? | Seven years. |
| DW650-12 | What information should I provide when contacting support about the SmartHome DW-650 dishwasher? | Model number, serial number, and purchase date. |

For each answer, expand **Routing details**. Expect `appliances` /
`dishwashers`; inspect the retrieved passages for the relevant DW-650
manual text. An `ingested_...` chapter name is generated during
classification and need not match a chapter title in the PDF. A listed
source alone does not prove that the answer is supported.

Optional follow-up test: after DW650-07 ask **What should I check first?**
The answer should still refer to E14 and check whether the water supply tap
is open. Follow-ups are not part of the independent automated batch below.

## 3. Run automated validation

After the upload is **Indexed**, run this from the repository root in
PowerShell:

```powershell
cd routing_lab5
..\.venv\Scripts\python.exe scripts\run_batch_tests.py --dataset datasets\dishwasher_manual_file2_questions.json --output-dir outputs\dishwasher_manual_file2
```

The [question dataset](../../routing_lab5/datasets/dishwasher_manual_file2_questions.json)
contains the 12 questions, expected answers, facts, route, and expected
source filename. Each question runs independently through the routing graph;
this is not a replay of a chat conversation and does not upload the PDF.

Open `routing_lab5\outputs\dishwasher_manual_file2\batch_report.md` for
expected versus actual answers, retrieved sources, and scores.
`batch_results.csv` gives a one-row summary, and `manual_review.csv` is
available for your own verdicts. The routing score for these cases includes
a source check: the uploaded PDF must appear among the retrieved passages.
If it is missing, the test fails even if the answer contains the expected
words. This checks retrieval, not whether every claim is supported.

If DW650-01 returns the correct answer but also selects an unrelated topic
such as `customer_support`, its routing and overall scores will be marked
wrong. Routing may vary between runs; inspect the per-question details rather
than assuming a correct answer means a correct route.

The answer score uses deterministic fact matching, not a semantic judge.
Review failures for correct alternative wording and review passes for
unsupported or incorrect extra claims. Rerunning overwrites reports in this
output folder; manual review entries are preserved by test ID. LLM and
embedding calls can incur costs. MLflow tracing is optional and should be
started on demand before the backend or batch command if needed.
