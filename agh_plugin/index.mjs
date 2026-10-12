// ProQ2-EQ-Agent AGH plugin v5.2 (FROZEN - do not modify).
// Four tools: eq_analyze / eq_optimize / eq_confirm_candidate / eq_rollback.
// All logic lives in Python. This file is a thin stable wrapper.
// - ToolMeta has ALL 8 required fields (AGH checkToolMeta rejects missing keys).
// - Python via node:child_process execFile; project dir from PROQ2_PROJECT_DIR.

import { execFile } from 'node:child_process';

const Kind = Symbol.for('TypeBox.Kind');

// ---- helpers ---------------------------------------------------------------

function projectDir() {
  const dir = process.env.PROQ2_PROJECT_DIR;
  if (!dir) {
    throw new Error(
      'PROQ2_PROJECT_DIR is not set. Set it to the proq2-eq-agent project directory.'
    );
  }
  return dir;
}

function pythonBin() {
  if (process.env.PROQ2_PYTHON) return process.env.PROQ2_PYTHON;
  const dir = projectDir();
  // Windows venv layout first, then Unix.
  if (/^[a-zA-Z]:\\/.test(dir) || dir.includes('\\')) {
    return dir + '\\.venv\\Scripts\\python.exe';
  }
  return dir + '/.venv/bin/python';
}

function runPython(script, args) {
  return new Promise((resolve) => {
    const py = pythonBin();
    execFile(py, [script, ...args], { cwd: projectDir(), timeout: 600000 }, (err, stdout, stderr) => {
      if (err) {
        resolve({
          content: [{ type: 'text', text: 'Python error: ' + (stderr || err.message) }],
          structured: { status: 'error', message: stderr || err.message },
        });
        return;
      }
      // Try to parse stdout as JSON; fall back to raw text.
      let structured;
      try {
        structured = JSON.parse(stdout);
      } catch {
        structured = { status: 'ok', raw: stdout };
      }
      resolve({
        content: [{ type: 'text', text: stdout }],
        structured,
      });
    });
  });
}

// ---- schemas ---------------------------------------------------------------

function toolParams(props, required) {
  return {
    [Kind]: 'Object',
    type: 'object',
    properties: props,
    required,
    additionalProperties: false,
  };
}

const optimizeParams = toolParams(
  {
    instruction: {
      [Kind]: 'String',
      type: 'string',
      description: 'Natural-language EQ instruction, e.g. "make it brighter"',
    },
    dsp_plan: {
      [Kind]: 'String',
      type: 'string',
      description: 'DSP plan as JSON string from agent reasoning. Keys: target_intervals, dsp_scores, clap_weight, clap_prompt. Built by the agent, not Python. Example: "{\"target_intervals\":{...},\"dsp_scores\":{...}}"',
    },
  },
  ['instruction']
);

const emptyParams = toolParams({}, []);

// AGH ToolMeta: all 8 fields required (see packages/extension-api/src/tool.ts).
const dawWriteMeta = {
  isReadOnly: false,
  isDestructive: true,
  isConcurrencySafe: false,
  isOpenWorld: false,
  replay: 'never',
  costHint: undefined,
  deferLoading: false,
  requiresApproval: 'always',
};

const readMeta = {
  isReadOnly: true,
  isDestructive: false,
  isConcurrencySafe: true,
  isOpenWorld: false,
  replay: 'safe',
  costHint: undefined,
  deferLoading: false,
  requiresApproval: 'never',
};

// ---- plugin ----------------------------------------------------------------

export const eqTools = {
  inject: ['extension'],
  apply(ctx) {
    const agnes = ctx.extension();

    agnes.registerTool({
      name: 'eq_optimize',
      description:
        'Optimize Fruity Parametric EQ 2 in FL Studio for a natural-language instruction. ' +
        'Long-running (about 30 seconds, 30 iterations). Returns a JSON diagnostic report.',
      parameters: optimizeParams,
      meta: dawWriteMeta,
      async execute({ instruction, dsp_plan }) {
        const args = ['--instruction', instruction];
        if (dsp_plan) {
          const planStr = typeof dsp_plan === 'string' ? dsp_plan : JSON.stringify(dsp_plan);
          args.push('--dsp-plan', planStr);
        }
        return runPython('scripts/run_agent.py', args);
      },
    });

    agnes.registerTool({
      name: 'eq_analyze',
      description:
        'Measure current DSP baseline features from FL Studio audio. ' +
        'Call this BEFORE planning to get baseline values for target interval computation. ' +
        'Returns 10 DSP dimension values.',
      parameters: emptyParams,
      meta: readMeta,
      async execute() {
        return runPython('scripts/run_agent.py', ['--instruction', 'analyze', '--analyze-only']);
      },
    });

    agnes.registerTool({
      name: 'eq_confirm_candidate',
      description:
        'Confirm the proposed EQ candidate after the user listened and accepted it. ' +
        'Locks in the current state as the accepted baseline.',
      parameters: emptyParams,
      meta: readMeta,
      async execute() {
        return runPython('scripts/session_tool.py', ['confirm']);
      },
    });

    agnes.registerTool({
      name: 'eq_rollback',
      description:
        'Roll back the EQ to the last confirmed (accepted) state. ' +
        'Use when the user rejects the proposed candidate.',
      parameters: emptyParams,
      meta: dawWriteMeta,
      async execute() {
        return runPython('scripts/session_tool.py', ['rollback']);
      },
    });

    agnes.on('session_start', () => {
      agnes.ctx.log.info('eq_analyze / eq_optimize / eq_confirm_candidate / eq_rollback are available');
    });
  },
};
