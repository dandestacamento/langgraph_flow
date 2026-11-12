"""Human-in-the-loop interrupt/resume tests.

Out of scope for Phase 1 ("Basic routing"). These will be implemented in
Phase 3 ("Advanced orchestration") once the Approval Gate node and
LangGraph checkpointing are added to the graph (see
instructions/SmartHome_Appliances/9_dev_phase.md).
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Human-in-the-loop approval is implemented in Phase 3")
def test_approval_gate_interrupts_and_resumes():
    ...
