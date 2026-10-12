"""Unit tests: fl_bridge event-loop machinery (no MCP server needed)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.fl_bridge import MCPBridge, SimulatedBridge, BridgeError


def _stubbed_bridge():
    b = MCPBridge("false", [], {})
    seen = []

    async def fake_connect():
        seen.append(asyncio.get_running_loop())
        b._session = object()  # stand-in; real session comes from MCP

    b._connect_async = fake_connect
    return b, seen


def test_single_event_loop_for_lifetime():
    b, seen = _stubbed_bridge()
    b.connect()

    async def probe():
        seen.append(asyncio.get_running_loop())
        await asyncio.sleep(0)  # exercises loop-bound primitives
        return "ok"

    assert b._run_coro(probe()) == "ok"
    # connect() and later calls MUST share one loop; the old
    # asyncio.run-per-call pattern put them on different loops and broke
    # the stdio session ("Event loop is closed").
    assert seen[0] is seen[1]
    b.close()
    assert b._loop is None


def test_close_idempotent():
    b, _ = _stubbed_bridge()
    b.connect()
    b.close()
    b.close()  # must not raise


def test_call_before_connect_raises():
    b = MCPBridge("false", [], {})

    async def probe():
        return 1

    try:
        b._run_coro(probe())
    except BridgeError:
        pass
    else:
        raise AssertionError("expected BridgeError")


def test_unknown_tool_name_raises():
    b = MCPBridge("false", [], {})
    try:
        b._t("nope")
    except BridgeError:
        pass
    else:
        raise AssertionError("expected BridgeError")


def test_simulated_bridge_roundtrip():
    b = SimulatedBridge()
    assert b.set_param_verified("Band 2 Gain", 0.75) == 0.75
    assert b.get_param("Band 2 Gain") == 0.75
    b.play()
    assert b.is_playing()
    b.set_song_pos(12.5)
    assert b.get_song_pos() == 12.5
