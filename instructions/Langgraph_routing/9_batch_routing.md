I recommend adding a Batch Routing Test Runner to your existing langgraph_routing project in VS Code.

You should be able to edit 20 questions in one file, run a single command, and receive a detailed report showing how LangGraph routed each question, which documents it retrieved, which tools it called, and whether the final answer matched your ground truth.

The important part is to keep expected results, actual results, and your manual assessment separate. That way, you can investigate errors without overwriting the original test expectations.
1. Recommended files
Use these paths relative to your VS Code project folder:
File path	Purpose	Editable?
langgraph_routing/datasets/routing_test_questions.json	20 questions, expected answers, expected routes	Yes
langgraph_routing/scripts/run_batch_tests.py	Execute all questions through LangGraph	Code
langgraph_routing/outputs/batch_results.csv	One row per test with results and accuracy	Yes, for review
langgraph_routing/outputs/batch_details.json	Full routing decisions, tool calls, retrieved documents, traces	Generated
langgraph_routing/outputs/batch_report.md	Readable report explaining each test	Generated
langgraph_routing/outputs/manual_review.csv	Your assessment and comments	Yes
langgraph_routing/outputs/routing_graph.mmd	Mermaid diagram of the graph	Generated

The runner should preserve your manual comments across repeated test runs, using a stable test_id.
2. Example batch test output
Batch Routing Test Report
Illustrative only

20
Questions tested


17/20
Correct topic routes


15/20
Correct answers


3
Routing failures



Example test results
Test	Question topic	Route	Answer
T001	Python decorators		
T002	Azure NSG		
T003	Washing machine E21		
T004	Spark partitioning		
T005	Loan repayment		

Sample values illustrate the report layout; no LangGraph tests have been executed here.
For each test, your detailed report should show:
- Question and ground-truth answer.
- Expected topic, subtopic, chapter, and tools.
- Actual route taken, in execution order.
- The router's classification and recorded decision evidence.
- Documents and passages retrieved, including relevance scores when available.
- Final generated answer with citations.
- Automated accuracy assessment and failure category.
- Your manual verdict and comments.
For example, a failed answer may have the correct route but incorrect retrieval. You want the report to distinguish that from a genuinely incorrect route.
3. I've created a starter project with 20 ground-truth questions
LangGraph Routing Test Starter

20 questions, Python batch runner, output reports, review file, README


Download the starter project

After extracting it into your VS Code workspace, edit this file:

langgraph_routing/datasets/routing_test_questions.json

The 20 questions cover Python, Azure, data engineering, appliances, finance, customer support, multi-subtopic questions, and ambiguity handling.
Run the batch tests
Open the VS Code terminal inside langgraph_routing:
python scripts/run_batch_tests.py


This creates the output reports, but marks tests as NOT_RUN until you connect your existing LangGraph application.

Once Copilot creates the adapter connecting your graph:
python scripts/run_batch_tests.py --adapter my_graph_adapter


To test only selected questions:
python scripts/run_batch_tests.py --adapter my_graph_adapter --ids T001 T005 T020


Output files
The starter has generated these files:
- 20 editable test questions
- Batch test runner
- Detailed Markdown report
- CSV results
- Detailed JSON trace report
- Manual review and comments
The current reports contain expected information and indicate that actual graph execution has not yet occurred.
4. Copilot prompt to integrate this with your existing application
I have added the langgraph_routing batch testing starter project to my existing VS Code workspace.

Please integrate the batch testing framework with my existing LangGraph application.

Requirements:
1. Inspect my existing LangGraph graph, nodes, state schema, routers, RAG retrievers, and tools. Reuse the existing implementation instead of creating a second graph.
2. Create my_graph_adapter.py implementing run_question(question, test_id) using the actual compiled LangGraph application.
3. Execute each question independently with a unique thread ID to avoid unintended conversation-memory contamination.
4. Capture the actual execution path using LangGraph streaming events and state snapshots. Record:
   - Router classification
   - Topic and subtopic selected
   - Conditional branches taken
   - Agent nodes executed
   - Tool calls and outputs
   - Documents retrieved
   - Final answer
   - Errors, retries, and execution time
   - MLflow trace ID
5. Compare the actual results against datasets/routing_test_questions.json.
6. Record routing correctness separately from answer correctness. Do not treat a text mismatch as proof that an answer is factually incorrect.
7. Update outputs/batch_report.md with a readable explanation of each test, including expected and actual routes and supporting evidence.
8. Preserve comments in outputs/manual_review.csv when tests are rerun.
9. Add MLflow tracing and generate a Mermaid diagram of the graph.
10. Add a command-line option to run all questions or selected test IDs.
11. Never fabricate routing traces, accuracy scores, or tool results. If an execution or evaluation fails, record its actual error.
12. After integration, run all 20 questions, report the real results, and identify any routing or retrieval failures.
Please implement this incrementally, test the adapter first with T001, and then execute the full batch.




5. My suggested manual review workflow
After running the tests, open outputs/batch_report.md and inspect each question's execution details. Then record your judgment in outputs/manual_review.csv.

For example:
Test	Answer verdict	Route verdict	Your comments
T001	Correct	Correct	Correct Python agent
T002	Incorrect	Correct	Retrieved wrong chapter
T003	Correct	Incorrect	Answer correct, but unnecessary Azure agent
T004	Partial	Correct	Missing important explanation

These are example review entries, not actual results.

My recommendation: Start with these 20 questions and get the complete batch execution and reporting process working. Then expand to 100 questions, including deliberately confusing questions, multiple topics, conflicting documents, and multi-hop reasoning.

That will allow you to test not just whether LangGraph produces a correct answer, but whether it arrived at the answer through the appropriate routing and retrieval process.





routing_test_questions.jsonCoderun_batch_tests.pyCodebatch_report.mdDocument
3 more