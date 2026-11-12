8. Prompt to give GitHub Copilot in VS Code
You can paste this into Copilot Chat to start building the application.
Create a Python LangGraph application called "SmartHome Appliances CSR Assistant".

The application will simulate a customer service system for an Australian appliance retailer selling refrigerators, washing machines, dryers, dishwashers, ovens, and air conditioners.

Main objective: Demonstrate and test LangGraph's routing, conditional edges, tool calling, state management, parallel agent execution, loops, human-in-the-loop approval, and error handling.

Requirements:
1. Use Python, LangGraph StateGraph, and a Streamlit user interface.
2. Implement a central Intent Router that classifies customer messages using structured LLM output.
3. Create five specialist agents: Product, Technical Support, Warranty, Orders, and Returns.
4. Support routing to one agent or multiple agents for complex inquiries.
5. Use mock JSON data for products, customers, orders, warranties, inventory, and policies.
6. Implement tools for checking inventory, order status, warranty eligibility, and product details.
7. Use conditional edges for routing and troubleshooting loops.
8. Use parallel execution for inquiries involving multiple agents, with appropriate state reducers and a response aggregation node.
9. Implement LangGraph checkpointing for conversation persistence and human-in-the-loop approval using interrupts and resume commands.
10. Display the final recommended response to the CSR.
11. Add a Graph Execution Inspector showing:
    - Router classification and selected agents
    - Executed nodes and edges
    - Tool calls and results
    - State changes
    - Errors and retries
    - Execution duration
12. Add Mermaid graph visualization and optional MLflow tracing.
13. Write pytest tests for routing, multi-agent execution, error recovery, and interrupt/resume behavior.
14. Keep the application modular, with separate graph, agent, tool, data, and test modules.
Start by implementing the simplest working version with a router, Product Agent, Technical Agent, and Warranty Agent. Then incrementally add advanced workflows.

Use current LangGraph APIs, clear Python type hints, and explanatory comments. Do not use LangSmith. Ensure all external actions are simulated and no real customer transactions are performed.