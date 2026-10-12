"""Unit tests: MIDIBridge protocol with a fake mido + simulated FL script.

No real MIDI ports or FL Studio needed. The fake port's send() emulates
the FL-side script: it reads proq2_command.json and writes
proq2_response.json, exercising the full JSON roundtrip.
"""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.fl_bridge import BridgeError, MIDIBridge, make_bridge

PORT = "ProQ2Bridge"
EQ_PARAMS = {"Band 2 Gain": 0, "Band 2 Frequency": 1}
EQ_VALUES = {"Band 2 Gain": 0.5, "Band 2 Frequency": 0.25}


class FakeMessage:
    def __init__(self, type, **kwargs):
        self.type = type
        self.__dict__.update(kwargs)


class FakePort:
    """Emulates the FL-side script for a subset of actions."""

    def __init__(self, script_dir, fail_on=None):
        self.script_dir = script_dir
        self.fail_on = fail_on or set()
        self.sent = []
        self.closed = False

    def _respond(self, payload):
        with open(os.path.join(self.script_dir, "proq2_response.json"),
                  "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def send(self, msg):
        self.sent.append(msg)
        with open(os.path.join(self.script_dir, "proq2_command.json"),
                  encoding="utf-8") as f:
            cmd = json.load(f)
        action, params = cmd["action"], cmd["params"]
        if action in self.fail_on:
            return  # simulate FL not responding -> timeout
        if action == "ping":
            self._respond({"success": True, "version": "1.0"})
        elif action == "find_eq":
            self._respond({"success": True, "found": True, "track": 5,
                           "slot": 0, "name": "Fruity Parametric EQ 2"})
        elif action == "get_param":
            idx = params["param_index"]
            name = [n for n, i in EQ_PARAMS.items() if i == idx][0]
            self._respond({"success": True, "index": idx,
                           "value": EQ_VALUES[name]})
        elif action == "set_param":
            idx = params["param_index"]
            name = [n for n, i in EQ_PARAMS.items() if i == idx][0]
            EQ_VALUES[name] = params["value"]
            self._respond({"success": True, "index": idx,
                           "value": params["value"]})
        elif action == "list_params":
            self._respond({"success": True,
                           "params": [{"index": i, "name": n}
                                      for n, i in EQ_PARAMS.items()]})
        elif action == "get_tempo":
            self._respond({"success": True, "tempo": 120.0})
        elif action == "transport":
            c = params["cmd"]
            if c == "is_playing":
                self._respond({"success": True, "is_playing": True})
            elif c == "get_pos":
                self._respond({"success": True, "pos": 0})
            else:
                self._respond({"success": True})
        else:
            self._respond({"success": False,
                           "error": "unknown action: " + action})

    def close(self):
        self.closed = True


def _install_fake_mido(monkeypatch, port, fail_on=None, port_names=None):
    fake = types.ModuleType("mido")
    fake.Message = FakeMessage
    names = port_names if port_names is not None else [PORT, "loopMIDI Port"]
    fake.get_output_names = staticmethod(lambda: names)
    fake.open_output = staticmethod(
        lambda name: port if name in names else (_ for _ in ()).throw(
            IOError("no such port")))
    monkeypatch.setitem(sys.modules, "mido", fake)
    return fake


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port)
    b = MIDIBridge(PORT, script_dir=str(tmp_path), timeout_s=2.0)
    b.connect()
    yield b
    b.close()


def test_connect_finds_eq(bridge):
    assert (bridge._track, bridge._slot) == (5, 0)


def test_set_and_get_param(bridge):
    assert bridge.set_param("Band 2 Gain", 0.75) == 0.75
    assert bridge.get_param("Band 2 Gain") == 0.75


def test_set_param_verified_ok(bridge):
    assert bridge.set_param_verified("Band 2 Frequency", 0.3) == 0.3


def test_list_params(bridge):
    names = bridge.list_params()
    assert "Band 2 Gain" in names


def test_transport_and_tempo(bridge):
    assert bridge.get_tempo() == 120.0
    assert bridge.is_playing() is True
    bridge.play()
    bridge.stop()
    bridge.set_song_pos(0)
    assert bridge.get_song_pos() == 0


def test_trigger_note_sent(bridge):
    bridge.get_tempo()
    notes = [m for m in bridge._port.sent if m.type == "note_on"]
    assert notes and notes[-1].note == MIDIBridge.TRIGGER_NOTE


def test_unknown_port_raises(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port)
    b = MIDIBridge("Nope", script_dir=str(tmp_path), timeout_s=1.0)
    with pytest.raises(BridgeError, match="not found"):
        b.connect()


def test_fl_error_propagates(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port)
    b = MIDIBridge(PORT, script_dir=str(tmp_path), timeout_s=2.0)
    b.connect()
    with pytest.raises(BridgeError, match="FL script error"):
        b._command("bogus_action", {})


def test_timeout_when_fl_silent(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path), fail_on={"get_tempo"})
    _install_fake_mido(monkeypatch, port)
    b = MIDIBridge(PORT, script_dir=str(tmp_path), timeout_s=0.3)
    b.connect()
    with pytest.raises(BridgeError, match="timeout"):
        b.get_tempo()


def test_make_bridge_selects_midi(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port)
    cfg = {"bridge": "midi",
           "midi_bridge": {"port_name": PORT, "script_dir": str(tmp_path),
                           "timeout_s": 2.0}}
    b = make_bridge(cfg)
    assert isinstance(b, MIDIBridge)
    b.close()


def test_resolve_index_robust(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port)
    b = MIDIBridge(PORT, script_dir=str(tmp_path), timeout_s=2.0)
    # Simulate a Chinese FL: rebuild the index with Chinese names.
    b.connect()
    b._param_index = {"频段 2 增益": 7, "频段 2 频率": 8}
    assert b._resolve_index("频段 2 增益") == 7
    assert b._resolve_index(" 频段 2 增益 ") == 7  # stray whitespace
    with pytest.raises(BridgeError, match="param not found"):
        b._resolve_index("不存在的参数")
    b.close()


def test_port_prefix_match_loopmidi_suffix(tmp_path, monkeypatch):
    # loopMIDI/RtMidi expose "ProQ2Bridge 3"; config says "ProQ2Bridge".
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port,
                       port_names=["Microsoft GS Wavetable Synth 0",
                                   "ProQ2Bridge 3"])
    b = MIDIBridge("ProQ2Bridge", script_dir=str(tmp_path), timeout_s=2.0)
    b.connect()
    assert b._actual_port == "ProQ2Bridge 3"
    b.close()


def test_port_ambiguous_prefix_raises(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port,
                       port_names=["ProQ2Bridge 2", "ProQ2Bridge 3"])
    b = MIDIBridge("ProQ2Bridge", script_dir=str(tmp_path), timeout_s=1.0)
    with pytest.raises(BridgeError, match="multiple MIDI ports match"):
        b.connect()


def test_make_bridge_unknown_kind():
    with pytest.raises(BridgeError, match="unknown bridge kind"):
        make_bridge({"bridge": "telepathy"})


def test_resolve_index_fallback(tmp_path, monkeypatch):
    port = FakePort(str(tmp_path))
    _install_fake_mido(monkeypatch, port)
    b = MIDIBridge(PORT, script_dir=str(tmp_path), timeout_s=2.0)
    b.connect()
    # Simulate mojibake names that can't be matched...
    b._param_index = {"???": 0, "???": 1}
    # ...but the configured index fallback rescues it.
    b.set_index_fallbacks(1, 8, "频段 2 增益", "频段 2 频率")
    assert b._resolve_index("频段 2 增益") == 1
    assert b._resolve_index("频段 2 频率") == 8
    b.close()
