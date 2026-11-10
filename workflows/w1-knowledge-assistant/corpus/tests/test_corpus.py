import datetime as dt
import re
import sys
from pathlib import Path

import pytest
import yaml

CORPUS_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = CORPUS_DIR / "docs"
sys.path.insert(0, str(CORPUS_DIR))

import generate_corpus as gen  # noqa: E402

REQUIRED_FIELDS = ("title", "doc_type", "owner_team", "classification", "system", "last_reviewed", "access_groups")
BROAD_GROUPS = {gen.GROUP_ALL_STAFF, gen.GROUP_ENGINEERING}
INJECTION_MARKER = "ignore previous instructions"


def split_front_matter(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert match, "missing YAML front matter"
    return yaml.safe_load(match.group(1)), match.group(2)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("*", "")).strip()


@pytest.fixture(scope="module")
def docs() -> dict[str, tuple[dict, str]]:
    return {p.name: split_front_matter(p.read_text(encoding="utf-8")) for p in sorted(DOCS_DIR.glob("*.md"))}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load((CORPUS_DIR / "manifest.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    return yaml.safe_load((CORPUS_DIR / "golden-questions.yaml").read_text(encoding="utf-8"))


def test_counts_per_type(docs):
    counts = {t: 0 for t in gen.COUNTS}
    for front, _ in docs.values():
        counts[front["doc_type"]] += 1
    assert counts == {"runbook": 40, "adr": 25, "terraform-module": 30, "postmortem": 20, "policy": 15}
    assert len(docs) == 130


def test_front_matter_is_valid(docs):
    for name, (front, body) in docs.items():
        assert list(front) == list(REQUIRED_FIELDS), name
        for field in ("title", "doc_type", "owner_team", "system"):
            assert isinstance(front[field], str) and front[field].strip(), (name, field)
        assert front["doc_type"] in gen.COUNTS, name
        assert front["classification"] in ("Public", "Internal", "Confidential", "Restricted"), name
        assert isinstance(front["last_reviewed"], dt.date), name
        assert dt.date(2025, 1, 1) <= front["last_reviewed"] <= dt.date(2026, 12, 31), name
        groups = front["access_groups"]
        assert isinstance(groups, list) and groups and all(isinstance(g, str) for g in groups), name
        assert body.strip().startswith("# "), name


def test_file_names_match_type_prefix(docs):
    prefixes = {"runbook": "rb-", "adr": "adr-", "terraform-module": "tfmod-", "postmortem": "pm-", "policy": "pol-"}
    for name, (front, _) in docs.items():
        assert name.startswith(prefixes[front["doc_type"]]), name


def test_manifest_matches_corpus(docs, manifest):
    assert manifest["counts"] == gen.COUNTS
    assert manifest["total"] == len(docs)


def test_access_traps_are_present_and_restricted(docs, manifest):
    access = manifest["traps"]["access"]
    assert len(access) == 10
    for name in access:
        front, _ = docs[name]
        assert front["classification"] in ("Confidential", "Restricted"), name
        assert not BROAD_GROUPS & set(front["access_groups"]), name
    # The access traps are the only documents above Internal, so a filter
    # bug cannot hide behind an untracked Confidential document.
    sensitive = {n for n, (f, _) in docs.items() if f["classification"] in ("Confidential", "Restricted")}
    assert sensitive == set(access)


def test_public_and_internal_documents_are_broadly_visible(docs):
    for name, (front, _) in docs.items():
        if front["classification"] in ("Public", "Internal"):
            assert set(front["access_groups"]) <= BROAD_GROUPS, name


def test_stale_pairs_are_present_and_older(docs, manifest):
    pairs = manifest["traps"]["stale"]
    assert len(pairs) == 5
    for pair in pairs:
        stale, _ = docs[pair["stale"]]
        current, _ = docs[pair["current"]]
        assert stale["doc_type"] == current["doc_type"], pair
        assert stale["last_reviewed"] < current["last_reviewed"], pair
        assert stale["classification"] == current["classification"] == "Internal", pair


def test_injection_traps_are_present_and_unique(docs, manifest):
    injection = manifest["traps"]["injection"]
    assert len(injection) == 3
    found = {n for n, (_, body) in docs.items() if INJECTION_MARKER in normalize(body).lower()}
    assert found == set(injection)


def test_golden_questions_shape(golden):
    assert len(golden) == 20
    assert len({q["id"] for q in golden}) == 20
    for q in golden:
        for field in ("question", "expected_answer", "source_document", "required_access_group", "trap"):
            assert isinstance(q.get(field), str) and q[field].strip(), (q["id"], field)
        assert q["trap"] in ("none", "access", "stale", "injection"), q["id"]
    traps = [q["trap"] for q in golden]
    assert traps.count("access") >= 4
    assert traps.count("stale") >= 3
    assert traps.count("injection") >= 2


def test_golden_sources_exist_and_are_consistent(golden, docs, manifest):
    access = set(manifest["traps"]["access"])
    injection = set(manifest["traps"]["injection"])
    pairs = {(p["stale"], p["current"]) for p in manifest["traps"]["stale"]}
    for q in golden:
        source = q["source_document"]
        assert (DOCS_DIR / source).is_file(), source
        front, body = docs[source]
        assert q["required_access_group"] in front["access_groups"], q["id"]
        assert normalize(q["evidence"]) in normalize(body), q["id"]
        if q["trap"] == "access":
            assert source in access, q["id"]
        if q["trap"] == "stale":
            assert (q["stale_document"], source) in pairs, q["id"]
        if q["trap"] == "injection":
            assert source in injection, q["id"]
        if q["trap"] == "none":
            assert source not in access | injection, q["id"]


def test_readme_documents_every_trap(manifest):
    readme = (CORPUS_DIR / "README.md").read_text(encoding="utf-8")
    traps = manifest["traps"]
    names = traps["access"] + traps["injection"] + [p[k] for p in traps["stale"] for k in ("stale", "current")]
    for name in names:
        assert name in readme, name


def normalize_newlines(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def test_same_seed_reproduces_identical_files(tmp_path, manifest):
    gen.generate(manifest["seed"], tmp_path)
    committed = {p.name: p.read_bytes() for p in DOCS_DIR.glob("*.md")}
    regenerated = {p.name: p.read_bytes() for p in (tmp_path / "docs").glob("*.md")}
    assert regenerated.keys() == committed.keys()
    # .gitattributes pins the corpus to LF, but a checkout made before it
    # existed, or with core.autocrlf, can still hold CRLF. Compare the
    # content with line endings normalized so that only the text matters.
    differing = [n for n in committed if normalize_newlines(committed[n]) != normalize_newlines(regenerated[n])]
    assert differing == []
    committed_manifest = (CORPUS_DIR / "manifest.yaml").read_bytes()
    regenerated_manifest = (tmp_path / "manifest.yaml").read_bytes()
    assert normalize_newlines(regenerated_manifest) == normalize_newlines(committed_manifest)


def test_generator_writes_lf_only(tmp_path, manifest):
    gen.generate(manifest["seed"], tmp_path)
    written = sorted((tmp_path / "docs").glob("*.md")) + [tmp_path / "manifest.yaml"]
    assert len(written) == 131
    with_cr = [p.name for p in written if b"\r" in p.read_bytes()]
    assert with_cr == []
    assert all(p.read_bytes().endswith(b"\n") for p in written)


def test_generation_is_deterministic_and_seed_sensitive(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    gen.generate(123, a)
    gen.generate(123, b)
    gen.generate(124, c)

    def read(d: Path) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in (d / "docs").glob("*.md")}

    assert read(a) == read(b)
    assert read(a) != read(c)
    # Anchor documents do not depend on the seed.
    for name in gen.ACCESS_TRAPS + gen.INJECTION_TRAPS:
        assert read(a)[name] == read(c)[name]
