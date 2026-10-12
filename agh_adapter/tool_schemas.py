"""AGH tool schemas (v4.3)."""
TOOL_SCHEMAS = {
    "eq_optimize": {
        "description": "Optimize Fruity Parametric EQ 2 for a natural-language instruction.",
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string",
                                "description": "e.g. 'make this lead brighter'"},
                "mode": {"type": "string", "enum": ["full", "delta"],
                         "default": "full"},
            },
            "required": ["instruction"],
        },
    },
    "eq_confirm_candidate": {
        "description": "Confirm the proposed candidate after listening.",
        "parameters": {"type": "object", "properties": {}},
    },
    "eq_rollback": {
        "description": "Roll the plugin back to the last accepted state.",
        "parameters": {"type": "object", "properties": {}},
    },
}
