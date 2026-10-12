"""FL Studio bridge (v4.3).

All FL operations go through the OFFICIAL MIDI Scripting API modules
(plugins / transport / mixer) -- but that API only runs INSIDE FL Studio,
so external Python reaches it via an MCP server (PostFader recommended)
over a virtual MIDI channel. This module is the Python-side MCP client.

Tool names differ between MCP implementations; they are configurable in
config/agent_config.yaml (mcp.tools). After installing the MCP server run
    python scripts/dump_eq2_params.py --list-tools
to see the actual names, then adjust the config if needed.

A SimulatedBridge is included for offline testing of the agent logic
(no FL / MCP needed).
"""
import asyncio
import os
import time


class BridgeError(RuntimeError):
    pass


class BaseBridge:
    """Interface every bridge implements."""

    def list_params(self):
        raise NotImplementedError

    def get_param(self, name):
        raise NotImplementedError

    def set_param(self, name, norm_value):
        """Set 0..1 normalized value. Returns read-back normalized value."""
        raise NotImplementedError

    def set_param_verified(self, name, norm_value, retries=1):
        """Set + read back; retry once; raise BridgeError on mismatch."""
        last = None
        for _ in range(retries + 1):
            last = self.set_param(name, norm_value)
            if last is not None and abs(last - norm_value) < 1e-3:
                return last
            time.sleep(0.2)
        raise BridgeError(
            "read-back mismatch for %s: wrote %.4f got %s"
            % (name, norm_value, last))

    def get_tempo(self):
        raise NotImplementedError

    def get_song_length_beats(self):
        """Return song/pattern length in beats, or None if unsupported."""
        return None

    def get_song_pos(self):
        raise NotImplementedError

    def set_song_pos(self, pos):
        raise NotImplementedError

    def is_playing(self):
        raise NotImplementedError

    def play(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def list_tools(self):
        raise NotImplementedError

    def close(self):
        pass


class MCPBridge(BaseBridge):
    """Real bridge: talks to a local stdio MCP server (e.g. PostFader).

    All asyncio work runs on ONE dedicated event-loop thread for the whole
    bridge lifetime. (Creating a new loop per call would detach the
    ClientSession/stdio pipes created in connect() from their loop.)
    """

    def __init__(self, command, args, tool_names, timeout_s=30):
        self.command = command
        self.args = list(args)
        self.tools = dict(tool_names)
        self.timeout_s = timeout_s
        self._loop = None
        self._thread = None
        self._session = None
        self._stack = None

    def _t(self, key):
        name = self.tools.get(key)
        if not name:
            raise BridgeError("tool name not configured for: %s" % key)
        return name

    def _run_coro(self, coro, timeout=None):
        if self._loop is None:
            raise BridgeError("bridge not connected; call connect() first")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout if timeout is not None else self.timeout_s)

    def connect(self):
        import threading
        ready, holder = threading.Event(), {}

        def runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            holder["loop"] = loop
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=runner, daemon=True,
                                        name="mcp-event-loop")
        self._thread.start()
        if not ready.wait(timeout=10):
            raise BridgeError("could not start MCP event-loop thread")
        self._loop = holder["loop"]
        self._run_coro(self._connect_async())

    async def _connect_async(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as e:
            raise BridgeError(
                "the 'mcp' package is not installed (pip install mcp).") from e
        params = StdioServerParameters(command=self.command, args=self.args)
        from contextlib import AsyncExitStack
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(
            stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write))
        await self._session.initialize()

    async def _close_async(self):
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    def close(self):
        if self._loop is not None:
            try:
                self._run_coro(self._close_async(), timeout=10)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._loop, self._thread = None, None

    def list_params(self):
        import json
        return json.loads(self._call(self._t("list_plugin_params"), {}))

    def get_param(self, name):
        import json
        out = json.loads(self._call(self._t("get_plugin_param"),
                                    {"param": name}))
        if isinstance(out, dict):
            return float(out.get("value_normalized", out.get("value", 0)))
        return float(out)

    def set_param(self, name, norm_value):
        import json
        out = json.loads(self._call(self._t("set_plugin_param"),
                                    {"param": name,
                                     "value_normalized": float(norm_value)}))
        if isinstance(out, dict) and "value_normalized" in out:
            return float(out["value_normalized"])
        return self.get_param(name)

    def get_tempo(self):
        return float(self._call(self._t("get_tempo"), {}))

    def get_song_length_beats(self):
        try:
            resp = self._call(self._t("get_song_length_beats"), {})
            if isinstance(resp, dict) and "length_beats" in resp:
                return float(resp["length_beats"])
        except Exception:
            pass
        return None

    def get_song_pos(self):
        return float(self._call(self._t("get_song_pos"), {}))

    def set_song_pos(self, pos):
        self._call(self._t("set_song_pos"), {"position": float(pos)})

    def is_playing(self):
        return self._call(self._t("is_playing"), {}).strip().lower() in (
            "true", "1", "playing", "yes")

    def play(self):
        self._call(self._t("transport_play"), {})

    def stop(self):
        self._call(self._t("transport_stop"), {})

    def _call(self, tool, arguments):
        async def go():
            res = await self._session.call_tool(tool, arguments)
            parts = []
            for c in res.content:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
            return "\n".join(parts)
        return self._run_coro(asyncio.wait_for(go(), self.timeout_s))

    def list_tools(self):
        async def go():
            tools = await self._session.list_tools()
            return [(t.name, t.description) for t in tools.tools]
        return self._run_coro(asyncio.wait_for(go(), self.timeout_s))


class MIDIBridge(BaseBridge):
    """Direct MIDI bridge: no MCP server needed.

    Talks to FL Studio via a minimal controller script
    (fl_bridge/device_ProQ2Bridge.py) over a dedicated loopMIDI port:

      1. write {"action": ..., "params": {...}} to proq2_command.json
         in the script's Hardware/ProQ2Bridge directory,
      2. send MIDI note 127 on the bridge port,
      3. poll proq2_response.json for the result.

    The script resolves the Fruity Parametric EQ 2 location itself
    (find_eq scans mixer tracks), so the user only needs the EQ loaded
    on any mixer track. Requires: mido + python-rtmidi, loopMIDI port,
    FL MIDI Settings > Input > port enabled with Controller type
    "ProQ2Bridge".
    """

    TRIGGER_NOTE = 127
    POLL_INTERVAL = 0.02

    def __init__(self, port_name, script_dir=None, timeout_s=5.0):
        self.port_name = port_name
        self.timeout_s = timeout_s
        if script_dir:
            self.script_dir = script_dir
        else:
            self.script_dir = os.path.join(
                os.path.expanduser("~"), "Documents", "Image-Line",
                "FL Studio", "Settings", "Hardware", "ProQ2Bridge")
        self.command_file = os.path.join(self.script_dir,
                                         "proq2_command.json")
        self.response_file = os.path.join(self.script_dir,
                                          "proq2_response.json")
        self._port = None
        self._track = None
        self._slot = None
        self._param_index = None
        # Optional name -> index fallbacks (from config) if the names
        # reported by FL can't be matched (encoding issues).
        self._index_fallbacks = {}

    def set_index_fallbacks(self, gain_idx, freq_idx,
                            gain_name=None, freq_name=None):
        if gain_idx is not None and gain_name:
            self._index_fallbacks[gain_name] = int(gain_idx)
        if freq_idx is not None and freq_name:
            self._index_fallbacks[freq_name] = int(freq_idx)

    # -- lifecycle ----------------------------------------------------
    def connect(self):
        try:
            import mido
        except ImportError as e:
            raise BridgeError(
                "mido not installed (pip install mido python-rtmidi).") from e
        ports = mido.get_output_names()
        # loopMIDI/RtMidi append a numeric suffix to make port names unique
        # at the OS level (e.g. "ProQ2Bridge 3"). Accept an exact match
        # first, then a "<name> <N>" prefix match so the config can just
        # say "ProQ2Bridge".
        target = None
        if self.port_name in ports:
            target = self.port_name
        else:
            cands = [p for p in ports
                     if p == self.port_name
                     or p.startswith(self.port_name + " ")]
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                raise BridgeError(
                    "multiple MIDI ports match '%s': %s. Put the exact "
                    "name in midi_bridge.port_name."
                    % (self.port_name, cands))
        if target is None:
            raise BridgeError(
                "MIDI port '%s' not found. Available: %s. "
                "Create it in loopMIDI and keep loopMIDI running."
                % (self.port_name, ports))
        try:
            self._port = mido.open_output(target)
        except Exception as e:
            raise BridgeError("cannot open MIDI port '%s': %s"
                              % (target, e)) from e
        self._actual_port = target
        # ping proves the FL script is alive and the files are shared
        pong = self._command("ping", {}, timeout=self.timeout_s)
        if pong.get("version") != "1.0":
            raise BridgeError("unexpected ping response: %r" % (pong,))
        found = self._command("find_eq", {}, timeout=30.0)
        if not found.get("found"):
            raise BridgeError(
                "Fruity Parametric EQ 2 not found on any mixer track. "
                "Load it on a mixer track first.")
        self._track, self._slot = found["track"], found["slot"]
        # Build name -> index map once; thereafter address params by index
        # so no string comparison happens inside FL.
        resp = self._command("list_params", self._eq_params())
        self._param_index = {p["name"]: p["index"]
                             for p in resp.get("params", [])}
        if not self._param_index:
            raise BridgeError("EQ reported no parameters")

    def close(self):
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None

    # -- protocol -----------------------------------------------------
    def _command(self, action, params, timeout=None):
        import json
        if self._port is None:
            raise BridgeError("bridge not connected; call connect() first")
        try:
            os.makedirs(self.script_dir, exist_ok=True)
        except Exception as e:
            raise BridgeError("cannot create script dir %s: %s"
                              % (self.script_dir, e)) from e
        with open(self.command_file, "w", encoding="utf-8") as f:
            # ensure_ascii=False: write raw UTF-8 (param names may be
            # Chinese); avoids any \uXXXX round-trip issues on the FL side.
            json.dump({"action": action, "params": params}, f,
                      ensure_ascii=False)
        if os.path.exists(self.response_file):
            try:
                os.remove(self.response_file)
            except OSError:
                pass
        import mido
        try:
            self._port.send(mido.Message("note_on", note=self.TRIGGER_NOTE,
                                         velocity=127))
        except Exception as e:
            raise BridgeError("MIDI send failed: %s" % e) from e
        deadline = time.time() + (timeout if timeout is not None
                                  else self.timeout_s)
        while time.time() < deadline:
            if os.path.exists(self.response_file):
                try:
                    with open(self.response_file, encoding="utf-8") as f:
                        resp = json.load(f)
                except (OSError, ValueError):
                    time.sleep(self.POLL_INTERVAL)
                    continue
                try:
                    os.remove(self.response_file)
                except OSError:
                    pass
                if not resp.get("success"):
                    raise BridgeError("FL script error: %s"
                                      % resp.get("error"))
                return resp
            time.sleep(self.POLL_INTERVAL)
        raise BridgeError(
            "timeout waiting for FL Studio response to '%s' (>%.0fs). "
            "Is FL Studio running with the ProQ2Bridge script enabled on "
            "the '%s' MIDI port?" % (action, timeout or self.timeout_s,
                                     self.port_name))

    def _eq_params(self, extra=None):
        if self._track is None:
            raise BridgeError("EQ location unknown; call connect() first")
        p = {"track": self._track, "slot": self._slot}
        if extra:
            p.update(extra)
        return p

    def _resolve_index(self, name, fallback_index=None):
        """Map a param name to its index, robustly.

        The FL script reports names (which may be localized, e.g. Chinese);
        we resolve once at connect() time and thereafter address params by
        index, avoiding any string comparison inside FL.
        If name matching fails and a fallback_index is configured, use it.
        """
        if self._param_index is None:
            raise BridgeError("param map not built; call connect() first")
        if name in self._param_index:
            return self._param_index[name]
        want = name.strip().lower()
        for n, i in self._param_index.items():
            if n.strip().lower() == want:
                return i
        want_ns = "".join(want.split())
        for n, i in self._param_index.items():
            if "".join(n.strip().lower().split()) == want_ns:
                return i
        if fallback_index is not None:
            return int(fallback_index)
        # Configured index fallback for this exact name?
        if name in self._index_fallbacks:
            return self._index_fallbacks[name]
        raise BridgeError("param not found: %r; available: %r"
                          % (name, sorted(self._param_index)))

    # -- BaseBridge interface -----------------------------------------
    def list_params(self):
        resp = self._command("list_params", self._eq_params())
        return [p["name"] for p in resp.get("params", [])]

    def get_param(self, name):
        resp = self._command(
            "get_param",
            self._eq_params({"param_index": self._resolve_index(name)}))
        return float(resp["value"])

    def set_param(self, name, norm_value):
        resp = self._command(
            "set_param", self._eq_params(
                {"param_index": self._resolve_index(name),
                 "value": float(norm_value)}))
        return float(resp["value"])

    def get_tempo(self):
        return float(self._command("get_tempo", {})["tempo"])

    def get_song_length_beats(self):
        try:
            resp = self._command("get_song_length_beats", {})
            if isinstance(resp, dict) and "length_beats" in resp:
                return float(resp["length_beats"])
        except Exception:
            pass
        return None

    def get_song_pos(self):
        return float(self._command("transport", {"cmd": "get_pos"})["pos"])

    def set_song_pos(self, pos):
        self._command("transport", {"cmd": "set_pos", "pos": pos})

    def is_playing(self):
        return bool(self._command("transport",
                                  {"cmd": "is_playing"})["is_playing"])

    def play(self):
        self._command("transport", {"cmd": "play"})

    def stop(self):
        self._command("transport", {"cmd": "stop"})

    def list_tools(self):
        return [("midi_bridge",
                 "direct MIDI bridge to FL Studio (no MCP server)")]


def make_bridge(cfg):
    """Build and connect the configured bridge (cfg["bridge"]).

    "midi" (default): direct MIDIBridge, no MCP server needed.
    "mcp": MCPBridge via a stdio MCP server (e.g. PostFader).
    "simulate": in-memory SimulatedBridge (offline testing).
    """
    kind = cfg.get("bridge", "midi")
    if kind == "simulate":
        return SimulatedBridge()
    if kind == "midi":
        mb = cfg["midi_bridge"]
        b = MIDIBridge(mb["port_name"], mb.get("script_dir"),
                       mb.get("timeout_s", 5.0))
        # Optional index fallbacks if param-name matching fails
        # (e.g. encoding issues with localized names).
        eq = cfg.get("eq", {})
        b.set_index_fallbacks(eq.get("gain_param_index"),
                              eq.get("freq_param_index"),
                              eq.get("gain_param"), eq.get("freq_param"))
        # Multi-band: register all control param indices as fallbacks
        # (for mojibake names from Chinese FL).
        try:
            from core.param_mapping import build_control_params
            for cp in build_control_params(eq):
                if cp.get("index") is not None:
                    b._index_fallbacks[cp["name"]] = int(cp["index"])
        except Exception:
            pass
    elif kind == "mcp":
        mc = cfg["mcp"]
        b = MCPBridge(mc["command"], mc["args"], mc["tools"],
                      mc["timeout_s"])
    else:
        raise BridgeError("unknown bridge kind: %r" % (kind,))
    b.connect()
    return b


class SimulatedBridge(BaseBridge):
    """In-memory bridge for offline testing (no FL, no MCP)."""

    def __init__(self, param_names=("Band 2 Gain", "Band 2 Frequency")):
        self._params = {n: 0.5 for n in param_names}
        self._playing = False
        self._pos = 0.0
        self._tempo = 120.0

    def list_params(self):
        return [{"name": n, "value_normalized": v}
                for n, v in self._params.items()]

    def get_param(self, name):
        # Auto-create unknown params at default (for multi-band tests)
        if name not in self._params:
            self._params[name] = 0.5
        return float(self._params[name])

    def set_param(self, name, norm_value):
        self._params[name] = min(1.0, max(0.0, float(norm_value)))
        return self._params[name]

    def get_tempo(self):
        return self._tempo

    def get_song_pos(self):
        return self._pos

    def set_song_pos(self, pos):
        self._pos = float(pos)

    def is_playing(self):
        return self._playing

    def play(self):
        self._playing = True

    def stop(self):
        self._playing = False

    def list_tools(self):
        return [("simulated", "in-memory test bridge")]
