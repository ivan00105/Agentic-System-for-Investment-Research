"""The single research agent, evaluation condition B (REFERENCE §7): one agent with every tool,
plan → tool loop → draft → deterministic checker → one self-review pass → report. The run itself is
runner.research, shared with the analyst team (condition C, team.py)."""
from pathlib import Path
from typing import Callable

from .. import config
from ..model_access import ModelSettings
from ..tools.result import ToolContext
from .roles import SINGLE
from .runner import AgentRun, research
from .trace import Trace

CONDITION = "B (single agent)"


def run(question: str, client, settings: ModelSettings, context: ToolContext, *,
        max_steps: int = config.AGENT_MAX_STEPS, self_review_passes: int = config.AGENT_SELF_REVIEW_PASSES,
        trace_dir: Path | None = None, echo: Callable[[dict], None] | None = None,
        trace: Trace | None = None) -> AgentRun:
    """`trace` is one the host made already, so it knows the run ID before the run starts (the web app)."""
    return research(question, client, settings, context, SINGLE, trace or Trace.new(trace_dir, echo),
                    condition=CONDITION, max_steps=max_steps, self_review_passes=self_review_passes)
