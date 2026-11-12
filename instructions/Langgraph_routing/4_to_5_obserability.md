4. Observability: see what LangGraph is doing
I recommend combining three different observability tools.
Tool	Purpose	What you can inspect
Mermaid	Graph visualization	Nodes, conditional edges, branches
MLflow Tracing	Execution tracing	Agent calls, LLM calls, tool calls, timing, inputs/outputs
Custom Streamlit dashboard	Accuracy testing	Expected vs actual routes, failed tests, accuracy trends

MLflow is open source and can help you inspect agent execution without requiring LangSmith. Mermaid visualizes the graph structure, while your custom event logger should capture which edges were actually selected in each run.
Example routing accuracy dashboard
Routing Evaluation Dashboard
Illustrative data

94%
Topic accuracy


89%
Subtopic accuracy


86%
Retrieval Recall@5


82%
Answer correctness




0%25%50%75%100%L1L2L3L4L5L6L7L8L9L10









Illustrative results across progressively harder scenarios






For meaningful evaluation, track these metrics separately:
- Topic accuracy: Was the correct topic selected?
- Subtopic accuracy: Was the correct subtopic selected?
- Route precision and recall: Were all necessary agents selected, without unnecessary agents?
- Retrieval Recall@K: Did the correct supporting passages appear in the top K results?
- Answer correctness: Does the response match the expected facts?
- Groundedness: Are the response claims supported by cited documents?
- Latency and cost: How expensive was each route?
Do not rely solely on an LLM judging another LLM. Use deterministic assertions for routes, document IDs, tool calls, calculations, and known facts. An LLM judge can supplement these checks for nuanced answers.
5. How to make the accuracy tests meaningful
The most important design decision is to create a controlled knowledge base with ground-truth answers.

For example, create a fictional washing machine with these facts:
Field	Ground-truth value
Model	WM-500
Capacity	9 kg
Standard warranty	2 years
Motor warranty	10 years
Error E21	Drainage problem
Error E42	Door lock problem

Now place these facts in different chapters, with some intentionally similar information about other models.

Then test:

Question: "What does E21 mean on the WM-500, and is the repair covered under warranty?"

A successful execution must retrieve both the error-code chapter and the warranty chapter, identify that E21 means a drainage problem, and avoid claiming warranty coverage without enough information about the cause and purchase date.

This is much better than testing only whether the final answer sounds reasonable.

Also introduce deliberately difficult documents: similar product names, outdated chapters, conflicting versions, missing facts, and questions that cannot be answered from the knowledge base.

The application should sometimes respond "Insufficient information" instead of guessing.