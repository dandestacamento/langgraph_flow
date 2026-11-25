# LangGraph application diagrams

These diagrams show the compiled application workflows in Lab 7's copied
version 6 baseline. Nodes are named after their LangGraph counterparts.
The experimental comparison architectures are not shown.

## Chat workflow

The chat graph handles one conversation turn. A knowledge question invokes
the separate routing graph shown below.

```mermaid
flowchart TD
    __start__([Start]) --> check_input[check_input]
    check_input -->|Blocked| record_turn[record_turn]
    check_input -->|Allowed| condense[condense]
    condense -->|Conversation question| answer_from_history[answer_from_history]
    condense -->|Direct attachment question| answer_from_attachment[answer_from_attachment]
    condense -->|Knowledge question| invoke_routing_pipeline[invoke_routing_pipeline]
    answer_from_history --> check_output[check_output]
    answer_from_attachment --> check_output
    invoke_routing_pipeline --> check_output
    check_output --> record_turn
    record_turn --> __end__([End])
```

`check_input` and `check_output` are no-ops when guardrails are disabled.
The blocked-input path skips both answer generation and the output check.
When an attachment is present and the question is classified as directly
about it, the attachment path takes precedence over conversation history.

Source: [chat graph](../app/chat/graph.py).

## Knowledge routing workflow

```mermaid
flowchart TD
    __start__([Start]) --> complexity_router[complexity_router]
    complexity_router -->|Normal question| multihop_router[multihop_router]
    complexity_router -->|Hop subquestion| topic_router[topic_router]
    multihop_router -->|Multi-hop| multihop_agent[multihop_agent]
    multihop_router -->|Single-hop| topic_router
    multihop_agent --> __end__([End])
    topic_router -->|Ambiguous| clarification_agent[clarification_agent]
    topic_router -->|Not ambiguous| subtopic_router[subtopic_router]
    clarification_agent --> __end__
    subtopic_router --> chapter_selector[chapter_selector]
    chapter_selector --> rag_retriever[rag_retriever]
    rag_retriever --> tool_router[tool_router]
    tool_router -->|Selected topic| appliances_agent[appliances_agent]
    tool_router -->|Selected topic| azure_cloud_agent[azure_cloud_agent]
    tool_router -->|Selected topic| data_engineering_agent[data_engineering_agent]
    tool_router -->|Selected topic| python_agent[python_agent]
    tool_router -->|Selected topic| finance_agent[finance_agent]
    tool_router -->|Selected topic| customer_support_agent[customer_support_agent]
    tool_router -->|Selected custom topic| custom_topic_agent[custom_topic_agent]
    appliances_agent --> synthesis_agent[synthesis_agent]
    azure_cloud_agent --> synthesis_agent
    data_engineering_agent --> synthesis_agent
    python_agent --> synthesis_agent
    finance_agent --> synthesis_agent
    customer_support_agent --> synthesis_agent
    custom_topic_agent --> synthesis_agent
    synthesis_agent --> __end__
```

- `tool_router` fans out to one agent per selected topic; multiple agents
  can run in parallel. Tool selection and execution happen inside that node.
- `multihop_agent` invokes the routing graph for each hop, rather than
  following an explicit graph edge back to the start. Hop subquestions skip
  `multihop_router` to prevent nested multi-hop recursion.
- Chapter selection is recorded for inspection; retrieval is scoped by
  topic and subtopic, not limited to the selected chapter.

Sources: [routing graph](../app/graph.py),
[multi-hop agent](../app/agents/multihop_agent.py).

## Document ingestion workflow

Knowledge-base uploads use a separate graph. Each conditional step moves to
`finish` when it has set a terminal outcome; classification may request
review, while other steps can fail.

```mermaid
flowchart TD
    __start__([Start]) --> validate[validate]
    validate -->|Continue| extract[extract]
    validate -->|Terminal outcome| finish[finish]
    extract -->|Continue| classify[classify]
    extract -->|Terminal outcome| finish
    classify -->|Continue| chunk[chunk]
    classify -->|Review or failure| finish
    chunk -->|Continue| index[index]
    chunk -->|Terminal outcome| finish
    index -->|Continue| validate_retrieval[validate_retrieval]
    index -->|Terminal outcome| finish
    validate_retrieval -->|Continue| publish[publish]
    validate_retrieval -->|Terminal outcome| finish
    publish --> finish
    finish --> __end__([End])
```

Source: [ingestion graph](../app/ingestion/graph.py).
