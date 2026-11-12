7. Copilot prompt to build the project
This is the prompt I would give GitHub Copilot in VS Code.
Build LangGraph Routing Accuracy Lab
Create a complete Python project in a folder named langgraph_routing.
Objective
Build a LangGraph application to test, visualize, measure, and improve routing accuracy across multiple topics, subtopics, chapters, file types, agents, and tools.

The application must progress from simple routing scenarios to advanced multi-agent and multi-hop RAG workflows.

Prioritize factual accuracy, reproducible testing, and detailed observability over chatbot appearance.
1. Knowledge base
Create a knowledge_base directory with at least six topics:
- Appliances
- Azure Cloud
- Data Engineering
- Python
- Finance
- Customer Support
Each topic must contain at least three subtopics. Each subtopic must contain at least three Markdown chapters with meaningful educational or fictional reference content.

Include some JSON, CSV, and TXT documents.

Add YAML metadata identifying topic, subtopic, chapter, document ID, and version.

Include overlapping terminology, similar document titles, conflicting document versions, and deliberately unanswerable questions to challenge routing and retrieval.

Generate a ground-truth dataset containing verified answers and the expected topics, subtopics, chapters, source passages, and tools.
2. LangGraph architecture
Use LangGraph StateGraph with typed shared state.

Implement:
- Complexity Router
- Topic Router
- Subtopic Router
- Chapter Selector
- RAG Retriever
- Tool Router
- Multi-Agent Planner
- Evidence Aggregator
- Answer Generator
- Answer Validator
- Error Recovery Node
Use conditional edges, parallel branches, state reducers, loops, and checkpointing where appropriate.

Use structured LLM outputs for classification and routing.

Support single-topic, multi-topic, multi-chapter, ambiguous, and multi-hop questions.
3. RAG
Implement document ingestion, Markdown-aware chunking, embeddings, metadata filtering, vector retrieval, optional reranking, and source citations.

Use Chroma or FAISS as the local vector store.

Ensure retrieved passages retain their document IDs, chapter IDs, and source locations.

Do not generate unsupported answers. If evidence is insufficient, request clarification or explicitly report insufficient information.
4. Observability
Use Mermaid for graph visualization and MLflow for tracing.

Do not use LangSmith.

Create a Streamlit dashboard displaying:
- User question
- Expected route
- Actual route
- Topic and subtopic selection
- Chapter selection
- Agent execution sequence
- Conditional edges selected
- Tool calls and results
- Retrieved documents and passages
- State changes
- LLM prompts and responses where appropriate
- Execution time
- Token usage and estimated cost where available
- Final answer with citations
- Routing and answer evaluation results
Capture execution traces from actual LangGraph events rather than inventing execution paths.
5. Testing scenarios
Create ten levels of tests:
1. Simple topic routing
2. Subtopic routing
3. Chapter routing
4. Single-topic RAG
5. Ambiguous questions
6. Multi-chapter retrieval
7. Multi-topic parallel routing
8. Tool selection and execution
9. Complex multi-hop reasoning
10. Error recovery and fallback
Create at least ten test questions per level, for a minimum of 100 questions.

Each test must include expected routes and independently verified reference facts.

Use pytest for deterministic assertions and MLflow for experiment tracking.
6. Evaluation
Implement metrics for:
- Topic accuracy
- Subtopic accuracy
- Chapter accuracy
- Route precision, recall, and F1
- Retrieval Recall@K
- Answer correctness
- Groundedness
- Tool selection accuracy
- Latency
- Token usage and cost
Create confusion matrices and failure analysis reports.

Compare three routing architectures:

A. Single LLM Router
B. Hierarchical Router
C. Hybrid Router with multi-agent planning and validation

Use the same test dataset for all three architectures.
7. Continuous improvement
When a test fails, save the question, expected route, actual route, retrieved documents, answer, and trace ID.

Classify failures as routing, retrieval, generation, validation, or tool errors.

Allow rerunning individual failed tests.

Avoid changing prompts based only on the test set. Maintain separate development and held-out evaluation datasets.
8. Development requirements
Use Python, LangGraph, LangChain where helpful, Streamlit, MLflow, pytest, and Mermaid.

Provide:
- Modular source code
- requirements.txt or pyproject.toml
- .env.example
- README.md
- Sample knowledge base
- Test datasets
- Automated test scripts
- Clear VS Code setup instructions
9. Implementation sequence
Implement one level at a time.

Start with Level 1 and ensure it works before proceeding to Level 2.

At each level:
1. Implement the workflow.
2. Generate test cases.
3. Execute automated tests.
4. Record actual routing traces.
5. Compare expected and actual results.
6. Investigate failures.
7. Fix verified problems.
8. Run regression tests.
9. Continue to the next level.
Do not claim a test passed unless it was actually executed.

Do not skip failing tests or fabricate evaluation metrics.

Start by creating the project structure, generating the controlled knowledge base, implementing the first router, and running Level 1 tests.




8. My recommended starting configuration
Component	Recommendation
Python	3.11 or 3.12
Framework	LangGraph
Model	Configurable OpenAI model or Ollama
Embeddings	Sentence Transformers for local testing
Vector database	Chroma
Observability	MLflow
Graph visualization	Mermaid
Dashboard	Streamlit
Testing	pytest
Evaluation	Deterministic metrics + optional LLM judge
Development	VS Code + GitHub Copilot

I would begin with 100 carefully constructed questions across 10 levels, rather than thousands of randomly generated questions. Use an initial target of at least 95% topic routing accuracy on held-out tests, while measuring subtopic, retrieval, and answer accuracy independently. This is a target, not a guaranteed outcome.

The most valuable feature of this project will be the ability to select a failed question and see exactly where the failure occurred: the topic router, subtopic router, chapter selector, retriever, tool execution, or answer generator.

That turns langgraph_routing into a genuine LangGraph routing benchmark and debugging laboratory, rather than simply a multi-agent RAG chatbot.