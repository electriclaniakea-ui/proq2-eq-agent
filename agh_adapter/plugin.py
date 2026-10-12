"""AGH adapter (v4.3): thin Python-side wrapper -> core.agent.

Two integration paths with Agnes Harness:
- agh_plugin/ (JS, recommended): the REAL AGH backend tool plugin. Registers
  eq_optimize / eq_confirm_candidate / eq_rollback via agnes.registerTool
  and shells out to scripts/. Use this for the competition.
- This file: Python-side local path (e.g. embedding the agent in another
  Python runtime). Kept for completeness; NOT the AGH plugin itself.

Everything else lives in core/ and does not import AGH. To port to another
runtime, rewrite the ~100 lines below.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.agent import Agent  # noqa: E402


def build_agent(deps):
    """deps: dict with keys config, bridge, audio, planner, session,
    param_mapping, clap (optional). Returns a wired Agent."""
    return Agent(config=deps["config"], bridge=deps["bridge"],
                 audio=deps["audio"], planner=deps["planner"],
                 session=deps["session"],
                 param_mapping=deps["param_mapping"],
                 clap=deps.get("clap"))


def register_tools(agent):
    """Return AGH tool definitions. The host runtime calls these."""

    def eq_optimize(instruction, mode="full"):
        """Optimize the EQ for a natural-language instruction."""
        return agent.run(instruction, mode=mode)

    def eq_confirm_candidate():
        """User confirmed the candidate after listening."""
        return agent.session.confirm_candidate()

    def eq_rollback():
        """Roll the plugin back to the accepted state."""
        return agent.session.rollback()

    return {"eq_optimize": eq_optimize,
            "eq_confirm_candidate": eq_confirm_candidate,
            "eq_rollback": eq_rollback}
