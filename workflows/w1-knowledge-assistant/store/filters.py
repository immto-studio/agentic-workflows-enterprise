"""W1's access filter in each platform's query language, offline (W1-D12, "Where Google and Microsoft differ").

Chapter 10. The test is the same everywhere: the chunk's `access_groups` share at least one group
with the caller's. What differs is how a query says it, and the limits on saying it. Each function
below takes the groups that matter, the caller's groups that gate some page, and returns the
filter in one platform's form; the facts and limits are in W1's fact sheet,
whose pages are under chapter 10 in LINKS.md.

- Amazon Bedrock Knowledge Bases: `listContains` on a string list, OR-ed with `orAll`. An `orAll`
  needs at least two members, takes at most five, and nests one level, so one filter holds at most
  twenty-five groups (sections A and B). Bedrock says list operators are "best supported" on
  OpenSearch Serverless; on S3 Vectors the list form is unconfirmed, and a single-valued attribute
  with `equals` avoids it while each page has one group.
- Amazon S3 Vectors queried directly: `$eq` on an array matches any element; each value costs one
  of the hundred constraints an ENHANCED index accepts.
- Azure AI Search: `search.in` over a string collection, one clause whatever the number of values.
- Google Agent Search (formerly Vertex AI Search): `ANY(...)` on an indexable string array.
- sqlite-vec, the exit drill's second store: no list column, so the groups sit in a side table and
  the KNN query takes `chunk_id IN (SELECT ...)`, which filters before the search.

An empty list of groups is refused everywhere, because on several platforms an empty or missing
filter means everything.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

KEY = "access_groups"
BEDROCK_PER_LIST = 5
BEDROCK_MAX = BEDROCK_PER_LIST * BEDROCK_PER_LIST  # one level of nesting
S3_VECTORS_MAX_CONSTRAINTS = 100
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # group names and object IDs, nothing to escape


class NoReadableGroups(ValueError):
    """The caller holds no group that gates a page: make no retrieval call at all."""


class TooManyGroups(ValueError):
    """More groups than one query can carry on this platform: split the query and merge by score."""


def _checked(groups: Sequence[str]) -> list[str]:
    names = sorted(set(groups))
    if not names:
        raise NoReadableGroups("no group to filter on")
    bad = [g for g in names if not NAME.match(g)]
    if bad:
        raise ValueError(f"group names a filter can't carry safely: {bad}")
    return names


def bedrock(groups: Sequence[str]) -> dict[str, Any]:
    """A `RetrievalFilter` for `retrievalConfiguration.vectorSearchConfiguration.filter`."""
    names = _checked(groups)
    if len(names) > BEDROCK_MAX:
        raise TooManyGroups(f"{len(names)} groups; one Bedrock filter holds at most {BEDROCK_MAX}")
    leaves = [{"listContains": {"key": KEY, "value": g}} for g in names]
    if len(leaves) == 1:
        return leaves[0]
    if len(leaves) <= BEDROCK_PER_LIST:
        return {"orAll": leaves}
    lists = [leaves[i:i + BEDROCK_PER_LIST] for i in range(0, len(leaves), BEDROCK_PER_LIST)]
    if len(lists[-1]) == 1:  # an orAll needs two members: move one leaf into the last list
        lists[-1].insert(0, lists[-2].pop())
    return {"orAll": [{"orAll": members} for members in lists]}


def s3_vectors(groups: Sequence[str]) -> dict[str, Any]:
    """A `QueryVectors` filter on an index whose `access_groups` metadata is an array."""
    names = _checked(groups)
    if len(names) > S3_VECTORS_MAX_CONSTRAINTS:
        raise TooManyGroups(f"{len(names)} constraints; an ENHANCED index accepts {S3_VECTORS_MAX_CONSTRAINTS}")
    clauses = [{KEY: {"$eq": g}} for g in names]
    return clauses[0] if len(clauses) == 1 else {"$or": clauses}


def azure_search(groups: Sequence[str]) -> str:
    """An OData `$filter` on a filterable, non-retrievable Collection(Edm.String) field."""
    return f"{KEY}/any(g: search.in(g, '{','.join(_checked(groups))}', ','))"


def agent_search(groups: Sequence[str]) -> str:
    """A Google Agent Search filter on an indexable string-array field."""
    return f"{KEY}: ANY(" + ",".join(f'"{g}"' for g in _checked(groups)) + ")"


def sqlite_vec(groups: Sequence[str]) -> tuple[str, list[str]]:
    """A WHERE fragment and its parameters for a vec0 KNN query, with the groups in chunk_acl."""
    names = _checked(groups)
    marks = ",".join("?" * len(names))
    return f"chunk_id IN (SELECT chunk_id FROM chunk_acl WHERE access_group IN ({marks}))", names
