4. Interactive routing test scenarios
Select a scenario to see the expected workflow. This can become the basis of your automated routing tests.
Choose a customer inquiry
Do you have a Bosch Series 6 dishwasher in stock?

My washing machine makes a loud banging noise during spinning.

My fridge stopped cooling. It's still under warranty. Can I get a replacement?

Where is order ORD-1045? It was supposed to arrive yesterday.

I want a refund for my faulty dishwasher.

Find a fridge under $1,500 with at least 400L capacity and delivery included.


Expected LangGraph execution
Router

Warranty Agent + Technical Agent

Policy Evaluator

Human Approval

CSR Response


Feature: Multi-agent routing, state merging and interrupts

Verify coverage and technical evidence; request approval before committing to replacement.