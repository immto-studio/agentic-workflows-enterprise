"""The access filter in each platform's form: shapes, limits, and no empty filter anywhere."""

from __future__ import annotations

import pytest

import filters
from filters import NoReadableGroups, TooManyGroups

RENDERERS = [filters.bedrock, filters.s3_vectors, filters.azure_search, filters.agent_search, filters.sqlite_vec]


def groups(n: int) -> list[str]:
    return [f"lm-group-{i:02d}" for i in range(n)]


def leaves(node: dict) -> list[str]:
    if "listContains" in node:
        return [node["listContains"]["value"]]
    return [leaf for child in node["orAll"] for leaf in leaves(child)]


def or_lists(node: dict) -> list[list]:
    if "orAll" not in node:
        return []
    return [node["orAll"]] + [inner for child in node["orAll"] for inner in or_lists(child)]


@pytest.mark.parametrize("render", RENDERERS)
def test_no_platform_gets_an_empty_filter(render):
    with pytest.raises(NoReadableGroups):
        render([])


@pytest.mark.parametrize("render", RENDERERS)
def test_names_a_filter_cannot_carry_safely_are_refused(render):
    with pytest.raises(ValueError):
        render(["lm-eng-all", "x') or true or ('"])


@pytest.mark.parametrize("n", [1, 2, 5, 6, 7, 11, 21, 24, 25])
def test_bedrock_keeps_every_or_list_between_two_and_five(n):
    node = filters.bedrock(groups(n))
    assert sorted(leaves(node)) == groups(n)
    assert all(2 <= len(members) <= 5 for members in or_lists(node))
    depth = 0 if n == 1 else 1 if n <= 5 else 2
    assert (bool(node.get("orAll")) and "orAll" in node["orAll"][0]) == (depth == 2)


def test_bedrock_refuses_more_than_one_filter_holds():
    with pytest.raises(TooManyGroups):
        filters.bedrock(groups(26))


def test_s3_vectors_counts_one_constraint_per_group():
    assert filters.s3_vectors(["lm-eng-all"]) == {"access_groups": {"$eq": "lm-eng-all"}}
    assert len(filters.s3_vectors(groups(3))["$or"]) == 3
    with pytest.raises(TooManyGroups):
        filters.s3_vectors(groups(101))


def test_the_string_forms():
    assert filters.azure_search(["lm-eng-all", "lm-all-staff"]) == \
        "access_groups/any(g: search.in(g, 'lm-all-staff,lm-eng-all', ','))"
    assert filters.agent_search(["lm-eng-all", "lm-all-staff"]) == 'access_groups: ANY("lm-all-staff","lm-eng-all")'
    assert filters.sqlite_vec(["lm-eng-all", "lm-all-staff"]) == (
        "chunk_id IN (SELECT chunk_id FROM chunk_acl WHERE access_group IN (?,?))", ["lm-all-staff", "lm-eng-all"])


def test_the_lab_never_needs_more_than_its_corpus_groups(fixed):
    corpus = {g for c in fixed for g in c.access_groups}
    assert len(corpus) == 11
    everyone = corpus | set(groups(40))  # an engineer in fifty groups
    assert len(leaves(filters.bedrock(sorted(everyone & corpus)))) == 11
