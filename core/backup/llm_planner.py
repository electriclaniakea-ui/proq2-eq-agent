"""LLM semantic planner (v4.3).

Calls an OpenAI-compatible chat API (Agnes). Assembles prompts from
config/prompts/, validates the returned JSON against the critic schema
(manual validation, no extra dependency), and archives the RAW response
to docs/planner_logs/<objective_id>.json for reproducibility.
"""
import json
import os
import time
import urllib.request

REQUIRED_TOP = ["objective_id", "status", "mode", "intent", "search_bounds",
                "target_intervals", "dsp_weights", "hard_constraints",
                "max_evaluations", "seed"]


class PlannerError(RuntimeError):
    pass


class LLMPlanner:
    def __init__(self, api_key, base_url, model, system_prompt_path,
                 user_template_path, log_dir, timeout_s=60, max_retries=3):
        if not api_key:
            raise PlannerError("AGNES_API_KEY is missing (see .env.example)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        with open(system_prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()
        with open(user_template_path, encoding="utf-8") as f:
            self.user_template = f.read()
        self.log_dir = log_dir
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        os.makedirs(log_dir, exist_ok=True)

    def _chat(self, system, user):
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.2,
        }).encode("utf-8")
        url = self.base_url + "/chat/completions"
        last_err = None
        for _ in range(self.max_retries):
            try:
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json",
                             "Authorization": "Bearer " + self.api_key})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    data = json.load(r)
                return data["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: BLE001 - retry then raise
                last_err = e
                time.sleep(2)
        raise PlannerError("LLM request failed after retries: %s" % last_err)

    @staticmethod
    def _extract_json(text):
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else t
            t = t.rsplit("```", 1)[0]
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end < 0:
            raise PlannerError("no JSON object in LLM response")
        return json.loads(t[start:end + 1])

    @staticmethod
    def _validate(cfg):
        for k in REQUIRED_TOP:
            if k not in cfg:
                raise PlannerError("planner config missing key: %s" % k)
        sb = cfg["search_bounds"]
        if not (sb["gain_db"][0] < sb["gain_db"][1]
                and sb["freq_hz"][0] < sb["freq_hz"][1]
                and sb["freq_hz"][0] > 0):
            raise PlannerError("invalid search_bounds")
        if cfg["status"] == "unsupported" and not cfg.get("unsupported_reason"):
            raise PlannerError("unsupported status needs unsupported_reason")
        return cfg

    def plan(self, instruction, baseline_features, objective_id, mode="full",
             history=None, accepted_params=None, plugin_limits=None):
        user = self.user_template.format(
            instruction=instruction,
            baseline_json=json.dumps(baseline_features, indent=2,
                                     ensure_ascii=False),
            history_json=json.dumps(history or [], ensure_ascii=False),
            accepted_params_json=json.dumps(accepted_params,
                                            ensure_ascii=False),
            objective_id=objective_id,
            mode=mode,
            plugin_limits_json=json.dumps(plugin_limits or {},
                                          ensure_ascii=False))
        raw = self._chat(self.system_prompt, user)
        # archive RAW response before any parsing (reproducibility)
        with open(os.path.join(self.log_dir, objective_id + ".json"),
                  "w", encoding="utf-8") as f:
            json.dump({"objective_id": objective_id, "mode": mode,
                       "instruction": instruction,
                       "raw_response": raw,
                       "timestamp": time.time()}, f, indent=2,
                      ensure_ascii=False)
        cfg = self._validate(self._extract_json(raw))
        if cfg["objective_id"] != objective_id:
            raise PlannerError("objective_id mismatch in planner response")
        return cfg
