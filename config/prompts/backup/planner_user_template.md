# User prompt template — semantic planner (v4.3)
# Filled by core/llm_planner.py. Placeholders: {instruction}, {baseline_json},
# {history_json}, {accepted_params_json}, {objective_id}, {mode}, {plugin_limits_json}

## Task
Generate a search configuration for the EQ parameter-optimization agent.

## User instruction (original language)
{instruction}

## Objective ID
{objective_id}

## Mode
{mode}
- "full": fresh search from current plugin state.
- "delta": incremental adjustment on top of accepted_params below.

## Current DSP baseline (all dimensions, with typical ranges)
{baseline_json}

## Accepted params from previous round (delta mode only; null otherwise)
{accepted_params_json}

## Conversation history (may be empty)
{history_json}

## Calibrated plugin limits (do not exceed)
{plugin_limits_json}

## Instructions
1. Run the capability check FIRST (see system prompt). If unsupported, return
   status "unsupported" with reason and suggestion.
2. Select dimensions honoring each dimension's FAILS condition.
3. Estimate target INTERVALS (not points) from baseline + instruction strength.
4. Score relevance 0-10 for EACH dimension per the scoring rules.
5. Set clap_weight per the CLAP weight rules.
6. Return ONLY the JSON object per the schema. No prose.
