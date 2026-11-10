"""Who is asking: the token's checks, and the membership table that decides the groups."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import timedelta

import jwt
import pytest

import access
from access import AccessError, MembershipFile, MembershipTable, caller_from_headers, issue, resolve, verify
from conftest import MEMBERSHIP, SECRET, USERS, fresh_table, printable, utc

TABLE = MembershipTable.load(MEMBERSHIP / "table.json")
SYNCED = utc(TABLE.synced_at)
FRESH = SYNCED + timedelta(hours=13)  # the afternoon after the nightly rebuild
STALE = SYNCED + timedelta(hours=37)  # the rebuild has failed for a day and a half
GROUP_IDS = {name: gid for gid, name in TABLE.group_names.items()}
BROAD = ["lm-all-staff", "lm-eng-all"]


def token(user: str, groups: list[str] | None = None, **kwargs) -> str:
    ids = None if groups is None else [GROUP_IDS[g] for g in groups]
    return issue(SECRET, USERS[user], f"{user}@larkspur.example", ids, **kwargs)


def caller(tok: str, now=FRESH):
    return resolve(verify(tok, SECRET), TABLE, now)


def claims(**changes) -> dict:
    base = {"iss": access.ISSUER, "aud": access.AUDIENCE, "oid": USERS["oncall.engineer"], "exp": 4102444800,
            "scp": access.SCOPE, "azp": access.W1_RUNTIME, "idtyp": "user"}
    return {k: v for k, v in {**base, **changes}.items() if v is not None}


# --- the token ----------------------------------------------------------------------------------

def test_a_lab_token_looks_like_the_on_behalf_of_token_and_passes():
    accepted = verify(token("oncall.engineer"), SECRET)
    assert accepted["scp"] == "Knowledge.Search" and accepted["azp"] == access.W1_RUNTIME
    assert "groups" not in accepted  # Larkspur's tokens for this server carry no groups claim (W1-D16)


def test_the_audience_is_the_servers_client_id_a_guid():
    # A v2.0 Entra token names the API by its client ID, not by an api:// URI.
    assert str(uuid.UUID(access.AUDIENCE)) == access.AUDIENCE


@pytest.mark.parametrize("why, bad", [
    ("another key", lambda: issue("another-secret-also-at-least-32-bytes", USERS["oncall.engineer"], "x")),
    ("expired", lambda: issue(SECRET, USERS["oncall.engineer"], "x", minutes=-5)),
    ("the old api:// audience", lambda: jwt.encode(claims(aud="api://w1-knowledge-server"), SECRET, "HS256")),
    ("another app's audience", lambda: jwt.encode(claims(aud=str(uuid.uuid4())), SECRET, "HS256")),
    ("another issuer", lambda: jwt.encode(claims(iss="https://elsewhere.example/v2.0"), SECRET, "HS256")),
    ("no oid", lambda: jwt.encode(claims(oid=None), SECRET, "HS256")),
    # the review's probe 5: an app-only token, with a role and no scope, from any client
    ("app-only", lambda: jwt.encode(claims(idtyp="app", scp=None, roles=["Some.Role"], azp="an-unrelated-daemon"),
                                    SECRET, "HS256")),
    ("idtyp app even with a scope", lambda: jwt.encode(claims(idtyp="app"), SECRET, "HS256")),
    ("no scp", lambda: jwt.encode(claims(scp=None), SECRET, "HS256")),
    ("another scope", lambda: jwt.encode(claims(scp="User.Read Files.Read"), SECRET, "HS256")),
    ("a client not on the allowlist", lambda: issue(SECRET, USERS["oncall.engineer"], "x", client=str(uuid.uuid4()))),
    ("no azp", lambda: jwt.encode(claims(azp=None), SECRET, "HS256")),
])
def test_tokens_that_fail_a_check_are_refused(why, bad):
    with pytest.raises(AccessError):
        verify(bad(), SECRET)


def test_the_scope_is_one_of_several():
    assert verify(jwt.encode(claims(scp="User.Read Knowledge.Search"), SECRET, "HS256"), SECRET)


# --- the groups ---------------------------------------------------------------------------------

def test_a_token_without_groups_leaves_the_table_to_decide():
    # The normal case: no groups claim, so the table alone decides.
    c = caller(token("vault.custodian"))
    assert c.groups == frozenset(BROAD + ["lm-vault-break-glass"]) and c.source == "table"
    assert caller(token("ea.lead")).groups == frozenset(BROAD + ["lm-ea-leads"])


def test_a_member_removed_today_stops_reading_once_the_delta_runs():
    # former.custodian was removed from lm-vault-break-glass after last night's rebuild; the
    # five-minute delta took the group off their row, and their token says nothing about groups.
    assert "lm-vault-break-glass" not in caller(token("former.custodian")).groups
    assert "lm-vault-break-glass" in caller(token("new.custodian")).groups


def test_an_unknown_user_holds_no_group():
    stranger = issue(SECRET, "00000000-0000-0000-0000-000000000000", "stranger@larkspur.example")
    assert caller(stranger).groups == frozenset() and caller(stranger).held == frozenset()


def test_a_stale_table_grants_only_the_broad_groups():
    c = caller(token("vault.custodian"), now=STALE)
    assert c.groups == frozenset(BROAD) and c.source == "stale table"
    assert c.held == frozenset(BROAD + ["lm-vault-break-glass"])  # what the custodian may type still counts
    assert caller(token("vault.custodian"), now=SYNCED + timedelta(hours=35)).source == "table"
    assert MembershipTable("never", {}, {}).stale(FRESH)  # a table of no known age is stale
    assert TABLE.stale(SYNCED - timedelta(hours=1))  # nor is a table stamped in the future


# Defense in depth: Larkspur's tokens carry no groups claim, but a token that did could only narrow.

def test_a_token_listing_groups_narrows_the_table_to_both():
    c = caller(token("vault.custodian", BROAD + ["lm-vault-break-glass"]))
    assert c.groups == frozenset(BROAD + ["lm-vault-break-glass"]) and c.source == "table and token"
    narrowed = caller(token("vault.custodian", BROAD))
    assert narrowed.groups == frozenset(BROAD) and "lm-vault-break-glass" in narrowed.held


def test_a_group_the_token_lists_but_the_table_lacks_grants_nothing():
    c = caller(token("oncall.engineer", BROAD + ["lm-vault-break-glass"]))
    assert "lm-vault-break-glass" not in c.groups


def test_overage_leaves_the_decision_to_the_table():
    c = caller(token("many.groups", overage=True))
    assert "lm-cloud-governance" in c.groups and c.source == "table (overage)"
    hasgroups = verify(token("many.groups"), SECRET) | {"hasgroups": True}
    assert resolve(hasgroups, TABLE, FRESH).source == "table (overage)"
    assert caller(token("many.groups", overage=True), now=STALE).source == "stale table (overage)"


def test_the_caller_comes_from_the_forwarded_header_only():
    tok = token("oncall.engineer")
    assert caller_from_headers({"x-larkspur-actor": tok}, TABLE, SECRET, FRESH).oid == USERS["oncall.engineer"]
    assert caller_from_headers({"X-Larkspur-Actor": f"Bearer {tok}"}, TABLE, SECRET, FRESH).groups == \
        frozenset(BROAD)
    with pytest.raises(AccessError, match="no X-Larkspur-Actor"):
        caller_from_headers({"authorization": f"Bearer {tok}"}, TABLE, SECRET, FRESH)
    with pytest.raises(AccessError, match="no request headers"):
        caller_from_headers(None, TABLE, SECRET, FRESH)  # stdio


def test_verify_and_resolve_stay_printable():
    printable(verify)
    printable(resolve)


# --- the table file -----------------------------------------------------------------------------

def write_table(folder, table: dict):
    path = folder / "table.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    return path


def test_the_server_reads_the_table_again_when_the_file_changes(tmp_path):
    table = fresh_table()
    path = write_table(tmp_path, table)
    membership = MembershipFile(path)
    first = membership.current()
    assert membership.current() is first  # unchanged file, same table
    removed = dict(table, members={k: v for k, v in table["members"].items() if k != USERS["vault.custodian"]})
    path.write_text(json.dumps(removed), encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert USERS["vault.custodian"] not in membership.current().members


def test_a_half_written_table_keeps_the_last_good_one(tmp_path):
    path = write_table(tmp_path, fresh_table())
    membership = MembershipFile(path)
    good = membership.current()
    path.write_text('{"synced_at": "2026-', encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert membership.current() is good
    path.unlink()
    assert membership.current() is good
