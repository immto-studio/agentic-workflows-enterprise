"""Step 5b's store: the pinned Garnet and its checks, a throwaway server, LiteLLM's limiter scripts on it, the alert
when it stops answering, the census's reading of it, and the configs that put step 4's gateway on it.

The tests that run Garnet skip when `capacity/garnet/` doesn't hold the pinned build (`python capacity/garnet.py`);
everything else needs no store, and nothing leaves 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import garnet
import pytest
import receiver
import store_hooks
import yaml

LAB = Path(__file__).resolve().parents[1]
CAPACITY = LAB / "capacity"
STEP4 = yaml.safe_load((LAB / "budget" / "litellm.config.yaml").read_text(encoding="utf-8"))
needs_garnet = pytest.mark.skipif(not garnet.EXE.is_file(), reason="no pinned Garnet in capacity/garnet/")


def config(name: str) -> dict:
    return yaml.safe_load((CAPACITY / name).read_text(encoding="utf-8"))


# --- the pin and the checks ------------------------------------------------------------------------------------

def test_the_pin_names_one_asset_one_digest_and_its_size():
    assert garnet.VERSION == "2.2.5" and garnet.ASSET == "win-x64-based-readytorun.zip"
    assert garnet.URL == "https://github.com/microsoft/garnet/releases/download/v2.2.5/win-x64-based-readytorun.zip"
    assert len(garnet.SHA256) == 64 and int(garnet.SHA256, 16) and garnet.SIZE == 26_186_101
    assert garnet.EXE == garnet.DIR / "net10.0" / "GarnetServer.exe" and garnet.DIR == CAPACITY / "garnet"
    assert "capacity/garnet/" in (LAB / ".gitignore").read_text(encoding="utf-8")


def test_only_the_servers_own_files_are_unpacked_and_nothing_outside_the_folder(tmp_path, monkeypatch):
    zipped = tmp_path / "fake.zip"
    with zipfile.ZipFile(zipped, "w") as z:
        for name in ("net10.0/GarnetServer.exe", "net10.0/lua54.dll", "net10.0/Service/Garnet.worker.exe",
                     "net10.0/extensions/GarnetJSON.dll", "README.md"):
            z.writestr(name, b"x")
    assert garnet.unpack(zipped, tmp_path / "out") == 2
    assert sorted(p.name for p in (tmp_path / "out" / "net10.0").iterdir()) == ["GarnetServer.exe", "lua54.dll"]
    escaping = tmp_path / "escaping.zip"
    with zipfile.ZipFile(escaping, "w") as z:
        z.writestr("net10.0/../../escape.exe", b"x")  # under a subfolder by its slashes, so never unpacked
    assert garnet.unpack(escaping, tmp_path / "out2") == 0
    monkeypatch.setattr(garnet, "wanted", lambda name: True)  # the second line, should the first ever let it by
    with pytest.raises(garnet.Mismatch):
        garnet.unpack(escaping, tmp_path / "out3")
    assert not (tmp_path / "escape.exe").exists()


def test_a_zip_or_a_program_other_than_the_pinned_one_is_refused(tmp_path):
    zipped = tmp_path / garnet.ASSET
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("net10.0/GarnetServer.exe", b"server")
        z.writestr("net10.0/lua54.dll", b"lua")
    with pytest.raises(garnet.Mismatch):
        garnet.check_zip(zipped)
    garnet.unpack(zipped, tmp_path)
    digest = garnet.sha256(zipped)
    assert garnet.verified(zipped, tmp_path / "net10.0", digest) == tmp_path / "net10.0" / "GarnetServer.exe"
    (tmp_path / "net10.0" / "lua54.dll").write_bytes(b"swapped")
    with pytest.raises(garnet.Mismatch, match="lua54.dll"):
        garnet.verified(zipped, tmp_path / "net10.0", digest)
    with pytest.raises(FileNotFoundError):
        garnet.verified(tmp_path / "absent.zip", tmp_path / "net10.0", digest)


def test_the_server_settings_keep_it_on_loopback_with_a_password_and_scripts_run_whole():
    s = garnet.settings(6390, "pw")
    assert (s["Address"], s["Port"], s["AuthenticationMode"], s["Password"]) == ("127.0.0.1", 6390, "Password", "pw")
    assert s["EnableLua"] is True and s["LuaTransactionMode"] is True and s["EnableAOF"] is False
    assert garnet.settings(6390, "pw", transaction_mode=False)["LuaTransactionMode"] is False
    assert garnet._command("AUTH", "pw") == b"*2\r\n$4\r\nAUTH\r\n$2\r\npw\r\n"


@needs_garnet
def test_a_throwaway_store_answers_with_its_password_only_empties_and_stops_by_its_id(tmp_path):
    garnet.verified()
    server = garnet.Server(tmp_path / "store")
    try:
        server.start()
        assert server.pid and not (tmp_path / "store" / "garnet.conf.tmp").exists(), "the settings file is deleted"
        assert garnet.ping(server.port, server.password) and not garnet.ping(server.port, "not-the-password")
        assert garnet.flushall(server.port, server.password)
    finally:
        pid = server.pid
        server.stop()
    assert pid and server.pid is None and not garnet.ping(server.port, server.password, timeout=0.5)


@needs_garnet
def test_litellms_check_and_increment_runs_whole_in_transaction_mode(tmp_path):
    """The probe's race, small: 200 calls at once over 40 connections against a limit of 50. Redis admits exactly 50;
    so does Garnet when it locks a script's keys."""
    import run_5b

    server = garnet.Server(tmp_path / "store")
    try:
        server.start()
        found = asyncio.run(run_5b.race(server.port, server.password, 200, 40, 50))
        scripts = asyncio.run(run_5b.probe_scripts(server.port, server.password))
    finally:
        server.stop()
    assert found == {"admitted": 50, "refused": 150, "errors": 0, "counter_after": 50}
    assert all(scripts["as_redis_answers"].values()), scripts["answers"]


# --- the alert ---------------------------------------------------------------------------------------------------

def test_the_watch_alerts_once_after_two_missed_pings_and_once_when_the_store_answers_again():
    w = store_hooks.Watch(misses=2)
    assert w.observe(None, 1.0) == (None, None, 0)
    assert w.observe("ConnectionRefusedError", 3.0) == (None, 3.0, 1)
    assert w.observe("ConnectionRefusedError", 5.0) == (store_hooks.UNREACHABLE, 3.0, 2)
    assert w.observe("TimeoutError", 7.0) == (None, 3.0, 3), "once, not at every miss"
    assert w.observe(None, 9.0) == (store_hooks.REACHABLE, 3.0, 3), "the outage that just ended"
    assert w.observe(None, 11.0) == (None, None, 0)
    assert store_hooks.Watch(misses=2).observe("x", 1.0)[0] is None, "one miss is not an outage"


def test_the_alert_names_the_store_and_never_carries_its_password():
    s = {"host": "127.0.0.1", "port": 6390, "password": "the-password", "webhook": "http://127.0.0.1:1/budget-alert"}
    down = store_hooks.StoreWatch.event(s, store_hooks.UNREACHABLE, "ConnectionRefusedError", 1793790000.0, 2,
                                        1793790002.0)
    up = store_hooks.StoreWatch.event(s, store_hooks.REACHABLE, None, 1793790000.0, 31, 1793790062.5)
    for body in (down, up):
        assert "the-password" not in json.dumps(body) and body["store"] == "127.0.0.1:6390"
        assert body["event_group"] == "platform"
    assert down["event"] == "limiter_store_unreachable" and down["failed_pings"] == 2
    assert "running on each worker's memory" in down["event_message"]
    assert up["event_message"] == "The limiter's store at 127.0.0.1:6390 answers again after 62.5 s."


def answering(answer: bytes):
    """A store's side of one ping: read it, answer, and let the client close first, so that the port can be bound
    again at once when the test brings the store back."""
    async def handle(reader, writer):
        await reader.read(100)
        writer.write(answer)
        await writer.drain()
        await reader.read()
        writer.close()

    return handle


async def fake_store(port_box: list, answer: bytes, port: int = 0) -> asyncio.base_events.Server:
    server = await asyncio.start_server(answering(answer), "127.0.0.1", port)
    port_box.append(server.sockets[0].getsockname()[1])
    return server


def test_the_ping_reads_auth_and_pong_and_names_what_went_wrong():
    async def go():
        box: list = []
        good = await fake_store(box, b"+OK\r\n+PONG\r\n")
        bad = await fake_store(box, b"-WRONGPASS invalid password\r\n\r\n")
        try:
            ok = await store_hooks.ping("127.0.0.1", box[0], "pw")
            wrong = await store_hooks.ping("127.0.0.1", box[1], "pw")
        finally:
            good.close()
            bad.close()
        closed = await store_hooks.ping("127.0.0.1", box[0], "pw", timeout=0.5)
        return ok, wrong, closed

    ok, wrong, closed = asyncio.run(go())
    assert ok is None and wrong.startswith("unexpected answer") and closed


def test_the_watch_sends_its_two_alerts_through_the_webhook_as_the_store_goes_and_comes_back(tmp_path, monkeypatch):
    sent: list[dict] = []

    async def record(s, body):
        sent.append(body)

    monkeypatch.setattr(store_hooks.StoreWatch, "send", staticmethod(record))

    async def go():
        box: list = []
        server = await fake_store(box, b"+OK\r\n+PONG\r\n")
        s = {"host": "127.0.0.1", "port": box[0], "password": "pw", "webhook": "http://127.0.0.1:1/budget-alert",
             "every_s": 0.05, "misses": 2, "file": str(tmp_path / "watch.jsonl")}
        task = asyncio.create_task(store_hooks.StoreWatch().watch(s))
        await asyncio.sleep(0.3)
        server.close()
        await server.wait_closed()
        deadline = time.monotonic() + 10  # a refused loopback connection takes up to two seconds on Windows
        while not sent and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        again = await fake_store([], b"+OK\r\n+PONG\r\n", port=box[0])
        deadline = time.monotonic() + 10
        while len(sent) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        task.cancel()
        again.close()

    asyncio.run(go())
    assert [b["event"] for b in sent] == ["limiter_store_unreachable", "limiter_store_reachable"]
    lines = [json.loads(line) for line in (tmp_path / "watch.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["alert"] for line in lines if line["alert"]] == ["limiter_store_unreachable", "limiter_store_reachable"]
    assert any(not line["ok"] for line in lines) and lines[-1]["ok"]


def test_the_receiver_sends_the_stores_alerts_to_the_platforms_on_call_alone():
    at = datetime(2026, 11, 4, 7, 0, tzinfo=timezone.utc)
    owners = {"w2-ops-assistant": "sam.okafor@larkspur.example"}
    for event, kind in (("limiter_store_unreachable", "the limiter's store unreachable"),
                        ("limiter_store_reachable", "the limiter's store answering again")):
        line = receiver.forward({"event": event, "event_group": "platform", "store": "127.0.0.1:6390"}, owners, at)
        assert line["forwarded_to"] == [receiver.PLATFORM_ONCALL] and line["kind"] == kind
    assert receiver.forward({"event": "soft_budget_crossed", "key_alias": "w2-ops-assistant"}, owners, at)[
        "forwarded_to"] == ["sam.okafor@larkspur.example", receiver.FINOPS], "budget alerts as before"


# --- the census's reading of the store ---------------------------------------------------------------------------

def store_line(t: float, held: dict | None = None, error: str | None = None) -> dict:
    if error:
        return {"t": t, "event": "store", "store_error": error}
    return {"t": t, "event": "store", "store_size": len(held or {}), "store_limiter": held or {}}


def test_the_stores_window_counts_as_evicted_only_when_it_goes_with_time_still_to_live():
    import run_5b

    window = "{api_key:h}:window"
    lived = [store_line(100.0, {window: ["1", 59.0]}), store_line(130.0, {window: ["1", 29.0]}),
             store_line(160.5, {}), store_line(161.0, {window: ["2", 60.0]})]
    found = run_5b.store_metrics(lived, {"w2-ops-assistant": "h"}, 100.0)
    assert found["keys"]["w2-ops-assistant"] == {"store_window_evicted_s": None, "store_evictions": 0,
                                                 "store_windows_seen": 2}
    cut = [store_line(100.0, {window: ["1", 59.0]}), store_line(110.0, {}), store_line(111.0, error="ConnectionError: x")]
    found = run_5b.store_metrics(cut, {"w2-ops-assistant": "h"}, 100.0)
    assert found["keys"]["w2-ops-assistant"]["store_window_evicted_s"] == 10.0
    assert found["store_errors"] == 1 and found["store_error_kinds"] == {"ConnectionError": 1}


def test_the_census_reads_the_store_off_the_call_path(tmp_path, monkeypatch):
    import census_hooks

    class Store:
        async def dbsize(self):
            return 3

        async def scan_iter(self, match, count):
            for name in ("{api_key:h}:tokens", "{api_key:h}:window"):
                yield name

        async def mget(self, names):
            return ["8000", "1793790000"]

        async def pttl(self, name):
            return 42_500

    class Down(Store):
        async def dbsize(self):
            raise ConnectionError("refused")

    read = asyncio.run(census_hooks.store_snapshot(Store()))
    assert read == {"store_size": 3, "store_limiter": {"{api_key:h}:tokens": ["8000", 42.5],
                                                       "{api_key:h}:window": ["1793790000", 42.5]}}
    assert asyncio.run(census_hooks.store_snapshot(Down())) == {"store_error": "ConnectionError: refused"}
    monkeypatch.delenv("CAPACITY_STORE_HOST", raising=False)
    hooks = census_hooks.Census(str(tmp_path / "census.jsonl"))
    hooks.start_store_census()
    assert hooks.store_task is None, "no store named, no reading of one"


# --- the configs -----------------------------------------------------------------------------------------------

STORE = {"host": "os.environ/CAPACITY_STORE_HOST", "port": "os.environ/CAPACITY_STORE_PORT",
         "password": "os.environ/CAPACITY_STORE_PASSWORD"}
ROUTER = {"redis_host": "os.environ/CAPACITY_STORE_HOST", "redis_port": "os.environ/CAPACITY_STORE_PORT",
          "redis_password": "os.environ/CAPACITY_STORE_PASSWORD"}


def test_the_store_configs_are_step_4s_gateway_with_the_store_and_the_alert_and_nothing_else():
    cfg = config("litellm.store.yaml")
    assert cfg["model_list"] == STEP4["model_list"]
    assert cfg["litellm_settings"]["callbacks"] == ["binding_hooks.hooks", "ch05_hooks.hooks", "store_hooks.hooks"]
    assert "cache" not in cfg["litellm_settings"], "no response from the store, ever"
    assert {k: v for k, v in cfg["litellm_settings"].items() if k != "callbacks"} == \
        {k: v for k, v in STEP4["litellm_settings"].items() if k != "callbacks"}
    assert cfg["router_settings"] == ROUTER and cfg["general_settings"]["coordination_redis"] == STORE
    assert {k: v for k, v in cfg["general_settings"].items() if k != "coordination_redis"} == STEP4["general_settings"]
    census = config("litellm.store-census.yaml")
    assert census["litellm_settings"]["callbacks"] == ["binding_hooks.hooks", "ch05_hooks.hooks", "census_hooks.hooks",
                                                       "store_hooks.hooks"]
    assert census["general_settings"] == cfg["general_settings"] and census["router_settings"] == ROUTER
    quiet = config("litellm.store-census-no-alerts.yaml")
    assert quiet["litellm_settings"] == census["litellm_settings"]
    assert quiet["general_settings"] == {k: v for k, v in census["general_settings"].items()
                                         if k not in ("alerting", "alert_types")}
    closed = config("litellm.store-census-fail-closed.yaml")
    assert closed["general_settings"] == {**census["general_settings"], "fail_closed_rate_limit_enforcement": True}
    assert {k: v for k, v in closed.items() if k != "general_settings"} == \
        {k: v for k, v in census.items() if k != "general_settings"}
    deployment, step5 = config("litellm.store-deployment.yaml"), config("litellm.deployment.yaml")
    assert deployment["model_list"] == step5["model_list"]
    assert deployment["router_settings"] == {**step5["router_settings"], **ROUTER}
    assert deployment["general_settings"] == {**step5["general_settings"], "coordination_redis": STORE}
    assert deployment["litellm_settings"]["callbacks"] == step5["litellm_settings"]["callbacks"] + ["store_hooks.hooks"]
