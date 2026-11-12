"""Human-in-the-loop interrupt/resume tests.

Still out of scope: Phase 2 added LangGraph checkpointing for conversation
memory, but the Approval Gate node (which pauses the graph with `interrupt`
and resumes via a CSR decision) is Phase 3 ("Advanced orchestration") work -
see instructions/SmartHome_Appliances/9_dev_phase.md.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Human-in-the-loop approval is implemented in Phase 3")
def test_approval_gate_interrupts_and_resumes():
    ...
