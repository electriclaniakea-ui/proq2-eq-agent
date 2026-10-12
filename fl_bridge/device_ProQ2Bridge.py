# name=ProQ2Bridge
# url=https://github.com/proq2-eq-agent

"""
ProQ2Bridge: minimal FL Studio MIDI controller script for ProQ2-EQ-Agent.

Runs INSIDE FL Studio. Receives commands from the external Python agent
via a JSON command file + a MIDI trigger note, executes them against FL's
official scripting API, and writes the result to a JSON response file.

Install:
  copy this file to
  %USERPROFILE%\\Documents\\Image-Line\\FL Studio\\Settings\\Hardware\\ProQ2Bridge\\
  then in FL: Options > MIDI Settings > Input > enable your loopMIDI port
  and set its Controller type to "ProQ2Bridge".

Protocol (same machine, shared files):
  1. Python writes {"action": ..., "params": {...}} to proq2_command.json
  2. Python sends MIDI note 127 (any channel) on the bridge port
  3. OnMidiMsg picks it up, dispatches, writes proq2_response.json
  4. Python polls for the response file (20ms interval)

Actions: ping, find_eq, list_params, get_param, set_param, get_tempo,
         transport {cmd: play|stop|is_playing|set_pos|get_pos}
"""

import json
import os
import sys
from pathlib import Path

import midi
import mixer
import plugins
import transport

TRIGGER_NOTE = 127
EQ_NAME_HINT = "parametric eq 2"


def _bridge_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", "~")) / "Documents" / \
            "Image-Line" / "FL Studio" / "Settings"
    else:
        base = Path.home() / "Documents" / "Image-Line" / "FL Studio" / \
            "Settings"
    return base / "Hardware" / "ProQ2Bridge"


BRIDGE_DIR = _bridge_dir()
COMMAND_FILE = BRIDGE_DIR / "proq2_command.json"
RESPONSE_FILE = BRIDGE_DIR / "proq2_response.json"


def OnInit():
    print("[ProQ2Bridge] initialized, watching " + str(COMMAND_FILE))


def OnDeInit():
    print("[ProQ2Bridge] deinitialized")


def OnIdle():
    pass


def OnMidiMsg(event):
    # Trigger note: mark handled so FL never treats it as musical input
    # or tries to map it to UI controls. Handle both note-on and note-off
    # (Python sends both); also swallow any other message on this port
    # to keep FL's generic MIDI mapper away from our bridge traffic.
    status = event.midiId & 0xF0
    if event.data1 == TRIGGER_NOTE and status in (0x80, 0x90):
        event.handled = True
        if status == 0x90 and event.data2 > 0:
            _execute_pending()
    elif status in (0x80, 0x90, 0xB0, 0xC0, 0xD0, 0xE0):
        # Any other channel-voice message arriving on the bridge port:
        # swallow it so FL doesn't try to link it to UI controls.
        event.handled = True


def _execute_pending():
    response = {"success": False, "error": None}
    try:
        if not COMMAND_FILE.exists():
            response["error"] = "no command file"
        else:
            cmd = json.loads(COMMAND_FILE.read_text(encoding="utf-8"))
            result = _dispatch(cmd.get("action", ""),
                               cmd.get("params", {}) or {})
            # A dispatch-level {"error": ...} must surface as failure,
            # otherwise Python would treat it as success and KeyError.
            if "error" in result:
                response = {"success": False, "error": result["error"]}
            else:
                response = {"success": True}
                response.update(result)
    except Exception as e:  # never let the script die on a bad command
        response = {"success": False, "error": str(e)}
    try:
        RESPONSE_FILE.write_text(json.dumps(response), encoding="utf-8")
    except Exception:
        pass


def _dispatch(action, params):
    if action == "ping":
        return {"version": "1.0"}
    if action == "find_eq":
        return _find_eq()
    if action == "list_params":
        return _list_params(params["track"], params["slot"])
    if action == "get_param":
        return _get_param(params["track"], params["slot"],
                          params.get("param_index"),
                          params.get("param_name"))
    if action == "set_param":
        return _set_param(params["track"], params["slot"],
                          params.get("param_index"),
                          params.get("param_name"),
                          float(params["value"]))
    if action == "get_tempo":
        return {"tempo": float(mixer.getCurrentTempo())}
    if action == "get_song_length_beats":
        # Returns song/pattern length in beats (pattern mode -> pattern length)
        try:
            length = transport.getSongLength(1)  # 1 = beats
            return {"length_beats": float(length)}
        except Exception as e:
            return {"error": "get_song_length failed: %s" % e}
    if action == "transport":
        return _transport(params.get("cmd", ""),
                          params.get("pos", 0))
    return {"error": "unknown action: " + str(action)}


def _find_eq():
    """Scan mixer tracks for Fruity Parametric EQ 2. Returns track/slot."""
    n_tracks = mixer.trackCount()
    for track in range(n_tracks):
        for slot in range(10):
            try:
                if not plugins.isValid(track, slot, True):
                    continue
                name = plugins.getPluginName(track, slot, False, True) or ""
                if EQ_NAME_HINT in name.lower():
                    return {"found": True, "track": track, "slot": slot,
                            "name": name}
            except Exception:
                continue
    return {"found": False}


def _param_index(track, slot, param_name):
    count = plugins.getParamCount(track, slot, True)
    want = param_name.strip().lower()
    names = []
    fallback = None
    for i in range(count):
        try:
            n = plugins.getParamName(i, track, slot, True) or ""
        except Exception:
            continue
        names.append(n)
        if n == param_name:
            return i, names
        if fallback is None and n.strip().lower() == want:
            fallback = i
    return fallback, names


def _list_params(track, slot):
    count = plugins.getParamCount(track, slot, True)
    out = []
    for i in range(count):
        try:
            out.append({"index": i,
                        "name": plugins.getParamName(i, track, slot, True)})
        except Exception:
            continue
    return {"params": out}


def _resolve_idx(track, slot, param_index, param_name):
    """Prefer an explicit index; fall back to name lookup."""
    if param_index is not None:
        try:
            return int(param_index), []
        except (TypeError, ValueError):
            pass
    if param_name:
        return _param_index(track, slot, param_name)
    return None, []


def _get_param(track, slot, param_index, param_name):
    idx, names = _resolve_idx(track, slot, param_index, param_name)
    if idx is None:
        return {"error": "param not found: %r; have: %r"
                % (param_name, names)}
    value = plugins.getParamValue(idx, track, slot, True)
    return {"index": idx, "value": float(value)}


def _set_param(track, slot, param_index, param_name, value):
    idx, names = _resolve_idx(track, slot, param_index, param_name)
    if idx is None:
        return {"error": "param not found: %r; have: %r"
                % (param_name, names)}
    value = max(0.0, min(1.0, float(value)))
    # NB: 5th arg is pickupMode (NOT useGlobalIndex); PIM_None disables
    # pickup so the value is applied immediately.
    plugins.setParamValue(value, idx, track, slot, midi.PIM_None, True)
    new_value = plugins.getParamValue(idx, track, slot, True)
    return {"name": param_name, "index": idx,
            "value": float(new_value)}


def _transport(cmd, pos):
    if cmd == "play":
        transport.start()
        return {"is_playing": bool(transport.isPlaying())}
    if cmd == "stop":
        transport.stop()
        return {"stopped": True}
    if cmd == "is_playing":
        return {"is_playing": bool(transport.isPlaying())}
    if cmd == "set_pos":
        # mode 1 = seconds
        transport.setSongPos(int(pos), 1)
        return {"ok": True}
    if cmd == "get_pos":
        return {"pos": transport.getSongPos(1)}
    return {"error": "unknown transport cmd: " + str(cmd)}
