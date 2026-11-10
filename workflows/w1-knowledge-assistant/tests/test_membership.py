"""The membership sync: tracked object IDs only, users only, a nightly rebuild and a five-minute delta."""

from __future__ import annotations

import copy
import json
from datetime import timedelta

import pytest

import group_map
import sync
from access import MembershipTable, issue, resolve, verify
from conftest import DELTA, EXPORT, GROUPS, MEMBERSHIP, SECRET, USERS, utc
from store import BM25

LAST_NIGHT = "2026-10-29T02:00:00Z"
LOOKALIKE = "df8a568d-afc1-59f2-b6d2-6072df7d4cf6"
SERVICE_PRINCIPAL = "bed0c88a-9d6a-54b3-b0de-b269988dc5bc"
DEVICE = "c1efa3f0-d2d6-59a9-9e60-f574f09f0efa"
GQ01 = "How many recovery key shards do we need to unseal prod Vault if KMS auto-unseal is down?"


@pytest.fixture()
def rebuilt():
    return sync.rebuild(copy.deepcopy(EXPORT), GROUPS, LAST_NIGHT)


def without_user(export: dict, oid: str) -> dict:
    """Graph after the user was deleted: no group lists them any more."""
    tonight = copy.deepcopy(export)
    for group in tonight["groups"]:
        group["transitiveMembers"] = [m for m in group["transitiveMembers"] if m["id"] != oid]
    return tonight


def test_a_lookalike_group_grants_nothing_and_is_reported(rebuilt, fixed, restricted_docs):
    # The review's probe 3: a second group named lm-vault-break-glass holds the on-call engineer.
    table, report = rebuilt
    lookalike = next(g for g in EXPORT["groups"] if g["id"] == LOOKALIKE)
    assert lookalike["displayName"] == "lm-vault-break-glass"
    assert USERS["oncall.engineer"] in {m["id"] for m in lookalike["transitiveMembers"]}
    assert table["members"][USERS["oncall.engineer"]] == ["lm-all-staff", "lm-eng-all"]
    assert LOOKALIKE not in table["groups"] and any(LOOKALIKE in line for line in report["lookalikes"])
    claims = verify(issue(SECRET, USERS["oncall.engineer"], "oncall.engineer@larkspur.example"), SECRET)
    caller = resolve(claims, MembershipTable.from_dict(table), utc(LAST_NIGHT) + timedelta(hours=1))
    assert "lm-vault-break-glass" not in caller.groups
    returned = {h.chunk.doc_id for h in BM25(fixed).search(GQ01, 10_000, caller.groups)}
    assert not returned & restricted_docs


def test_service_principals_devices_and_nested_groups_are_never_rows(rebuilt):
    table, report = rebuilt
    assert SERVICE_PRINCIPAL not in table["members"] and DEVICE not in table["members"]
    assert report["skipped"] == {"device": 1, "group": 1, "servicePrincipal": 1}
    assert set(table["members"]) <= set(USERS.values())


def test_a_nested_group_is_skipped_and_its_users_count_through_the_flat_list(rebuilt):
    # lm-eng-all is nested in lm-all-staff. Graph's transitiveMembers on lm-all-staff lists the
    # nested group itself and, flattened, its users; the sync keeps the users and skips the group.
    table, _ = rebuilt
    all_staff = next(g for g in EXPORT["groups"] if g["id"] == GROUPS.ids["lm-all-staff"])
    kinds = {m["@odata.type"] for m in all_staff["transitiveMembers"]}
    assert kinds == {"#microsoft.graph.group", "#microsoft.graph.user"}
    assert GROUPS.ids["lm-eng-all"] not in table["members"]
    assert len(table["members"]) == len(USERS) and all("lm-all-staff" in held for held in table["members"].values())


def test_rows_keep_the_reviewed_names_whatever_graph_calls_the_group():
    renamed = copy.deepcopy(EXPORT)
    vault = next(g for g in renamed["groups"] if g["id"] == GROUPS.ids["lm-vault-break-glass"])
    vault["displayName"] = "Vault custodians (break-glass)"
    table, report = sync.rebuild(renamed, GROUPS, LAST_NIGHT)
    assert "lm-vault-break-glass" in table["members"][USERS["vault.custodian"]]
    assert table["groups"][GROUPS.ids["lm-vault-break-glass"]] == "lm-vault-break-glass"
    assert any("Vault custodians" in line for line in report["renamed"])


def test_a_delta_applies_a_removal_and_an_addition(rebuilt):
    table, _ = rebuilt
    assert "lm-vault-break-glass" in table["members"][USERS["former.custodian"]]
    assert "lm-vault-break-glass" not in table["members"][USERS["new.custodian"]]
    after = sync.apply_delta(table, DELTA, "2026-10-29T14:05:00Z")
    assert "lm-vault-break-glass" not in after["members"][USERS["former.custodian"]]
    assert "lm-vault-break-glass" in after["members"][USERS["new.custodian"]]
    assert after["delta_applied_at"] == "2026-10-29T14:05:00Z" and after["synced_at"] == LAST_NIGHT


def test_a_delta_never_writes_a_device_or_a_service_principal(rebuilt):
    table, _ = rebuilt
    delta = {"value": [{"id": GROUPS.ids["lm-ea-leads"], "members@delta": [
        {"@odata.type": "#microsoft.graph.device", "id": DEVICE},
        {"@odata.type": "#microsoft.graph.servicePrincipal", "id": SERVICE_PRINCIPAL}]}]}
    assert sync.apply_delta(table, delta, "2026-10-29T14:05:00Z")["members"] == table["members"]


def test_a_nested_group_removed_by_a_delta_takes_its_users_with_it_within_minutes(rebuilt):
    # lm-eng-all leaves lm-all-staff. The delta names only the group, so the job reads
    # lm-all-staff's transitive members again: in this Graph, nobody is left in it.
    table, _ = rebuilt
    delta = {"value": [{"id": GROUPS.ids["lm-all-staff"], "members@delta": [
        {"@odata.type": "#microsoft.graph.group", "id": GROUPS.ids["lm-eng-all"], "@removed": {"reason": "deleted"}}]}]}
    reads = []

    def transitive(gid):
        reads.append(gid)
        return []

    after = sync.apply_delta(table, delta, "2026-10-29T14:05:00Z", transitive)
    assert reads == [GROUPS.ids["lm-all-staff"]]
    assert not any("lm-all-staff" in held for held in after["members"].values())
    assert all("lm-eng-all" in held for held in after["members"].values())  # the other groups stay


def test_a_nested_group_added_by_a_delta_brings_its_users(rebuilt):
    table, _ = rebuilt
    delta = {"value": [{"id": GROUPS.ids["lm-ea-leads"], "members@delta": [
        {"@odata.type": "#microsoft.graph.group", "id": "0b1d1a2c-1111-5222-8333-444455556666"}]}]}
    newcomer = {"@odata.type": "#microsoft.graph.user", "id": USERS["oncall.engineer"]}
    after = sync.apply_delta(table, delta, "2026-10-29T14:05:00Z", lambda gid: [newcomer])
    assert "lm-ea-leads" in after["members"][USERS["oncall.engineer"]]
    assert "lm-ea-leads" not in after["members"][USERS["ea.lead"]]  # Graph no longer lists them
    with pytest.raises(sync.SyncError, match="nested group"):
        sync.apply_delta(table, delta, "2026-10-29T14:05:00Z")  # nobody to ask: no guess


def test_a_deleted_user_survives_the_deltas_and_drops_out_at_the_rebuild(rebuilt):
    # Graph's delta doesn't report a member removed by deleting the user; only the rebuild sees it.
    table, _ = rebuilt
    gone = USERS["pci.operator"]
    after_delta = sync.apply_delta(table, DELTA, "2026-10-29T14:05:00Z")
    assert gone in after_delta["members"]
    tonight, _ = sync.rebuild(without_user(EXPORT, gone), GROUPS, "2026-10-30T02:00:00Z")
    assert gone not in tonight["members"]


def test_a_missing_tracked_group_stops_the_sync_and_keeps_the_old_table(tmp_path):
    broken = copy.deepcopy(EXPORT)
    broken["groups"] = [g for g in broken["groups"] if g["id"] != GROUPS.ids["lm-ea-leads"]]
    with pytest.raises(sync.SyncError, match="lm-ea-leads"):
        sync.rebuild(broken, GROUPS, LAST_NIGHT)
    export, table = tmp_path / "export.json", tmp_path / "table.json"
    export.write_text(json.dumps(broken), encoding="utf-8")
    table.write_text('{"synced_at": "old"}\n', encoding="utf-8")
    assert sync.main(["--export", str(export), "--out", str(table)]) == 1
    assert table.read_text(encoding="utf-8") == '{"synced_at": "old"}\n'


def test_a_tracked_group_deleted_in_a_delta_stops_the_sync(rebuilt):
    table, _ = rebuilt
    delta = {"value": [{"id": GROUPS.ids["lm-ea-leads"], "@removed": {"reason": "deleted"}}]}
    with pytest.raises(sync.SyncError, match="lm-ea-leads"):
        sync.apply_delta(table, delta, "2026-10-29T14:05:00Z")


def test_the_cli_rebuilds_then_applies_a_delta(tmp_path):
    out = tmp_path / "table.json"
    assert sync.main(["--out", str(out), "--at", LAST_NIGHT]) == 0
    assert sync.main(["--out", str(out), "--delta", str(MEMBERSHIP / "graph-delta.json"),
                      "--at", "2026-10-29T14:05:00Z"]) == 0
    table = json.loads(out.read_text(encoding="utf-8"))
    assert table["delta_applied_at"] == "2026-10-29T14:05:00Z"
    assert not list(tmp_path.glob("*.tmp"))  # the file was replaced whole
    for bad in ("tomorrow", "2026-10-29T02:00:00", "2026-10-29T02:00:00+02:00"):
        with pytest.raises(SystemExit):
            sync.main(["--out", str(out), "--at", bad])


def test_the_committed_table_is_last_nights_rebuild_with_todays_delta():
    committed = json.loads((MEMBERSHIP / "table.json").read_text(encoding="utf-8"))
    table, _ = sync.rebuild(EXPORT, GROUPS, committed["synced_at"])
    assert sync.apply_delta(table, DELTA, committed["delta_applied_at"]) == committed
    assert committed["broad"] == ["lm-all-staff", "lm-eng-all"]


def test_the_reviewed_map_is_checked_when_loaded(tmp_path):
    assert group_map.load().broad == {"lm-all-staff", "lm-eng-all"}
    bad = tmp_path / "groups.yaml"
    bad.write_text("groups:\n  a: {id: not-a-guid}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an object ID"):
        group_map.load(bad)
    same = "0681cfc3-4bd5-55aa-a29c-62f5f9c1304a"
    bad.write_text(f"groups:\n  a: {{id: '{same}'}}\n  b: {{id: '{same}'}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="two names"):
        group_map.load(bad)
