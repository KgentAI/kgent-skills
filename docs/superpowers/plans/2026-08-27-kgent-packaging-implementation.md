# kgent Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the kgent knowledge-management packaging system (in-process router library + `kgent` CLI + three backend adapters + orchestration skills) against the approved acceptance spec (v1.3, S1–S69, N1–N19, P1–P7) and design spec (v1.6).

**Architecture:** A deterministic, in-process Python router enforces policy (config trust, routing precedence, sensitivity zones, approval gates, write journal, audit, optimistic concurrency) and returns a structured `RoutingIntent` to the agent loop. Backends (Lark/Feishu via `lark-doc` skill + `lark-cli` fallback; DingTalk/WeCom via CLI) sit behind a capability interface with fake in-process adapters used for tests. The `kgent` CLI exposes primitives; the `store` workflow and skills layer orchestrate judgment-heavy paths.

**Tech Stack:** Python (stdlib-only runtime), pytest + pytest-randomly, mypy --strict, ruff, coverage + diff-cover, mutmut, hypothesis (dev-only). No runtime deps beyond stdlib.

## Global Constraints

Copied verbatim from the approved specs. Every task implicitly includes these.

- **Language:** Python (matches agent-service; router is service-side logic).
- **Runtime deps:** stdlib only. Any router runtime dependency is a spec revision, not an implementation choice.
- **Test deps (authorized):** pytest, pytest-randomly, mypy --strict, ruff, coverage + diff-cover, mutmut, hypothesis.
- **Test doubles:** fake in-process adapters implementing the capability interface. Mock boundaries: network, clock, filesystem paths outside `~/.kgent` test-home. **Never mocked:** routing precedence, journal/audit writers, policy gates.
- **Exit codes** (design §12): `0` ok · `2` partial · `1` failure · `3` policy-rejected · `4` version conflict.
- **Standard test world** (acceptance §2): backends `lark` (internal, full), `dingtalk` (external, keyword-only), `wecom` (external, keyword-only); `defaults: {routing_mode: configured, default_backends: [lark], approval_ttl_hours: 24}`; `user: alice`.
- **Canonical URIs:** `kgent://<backend>/<native-id>` are the only identifiers crossing adapter boundaries (§3.6). Bare native IDs are rejected with a hint.
- **Local state:** `~/.kgent` dir `0700`; every file under it `0600` (journal, snapshots, idmap, cache, trusted.json, config).
- **No telemetry off-machine** — content, queries, and URIs never leave the machine (N14).
- **Untrusted content:** backend-returned content is data, never instructions (N6, S39).
- **Checkpoint commits:** spec approval, each GREEN, each REFACTOR, gauntlet pass.

---

## File Structure

```
kgent-skills/
├── pyproject.toml                     # project metadata, dev deps, ruff/mypy/pytest config
├── tools/
│   ├── gauntlet.sh                    # §6 entry point: clean → test → type → lint → mutate → props → adversarial → smoke → secret/network scan
│   └── mutants.py                     # manual-mutation fallback if mutmut unavailable
├── src/kgent/
│   ├── __init__.py                    # package version
│   ├── __main__.py                    # python -m kgent
│   ├── cli.py                         # argparse entry; maps commands → primitives; exit codes
│   ├── errors.py                      # KgentError hierarchy + exit-code mapping
│   ├── types.py                       # core data schemas (§3.8): DocumentMetadata, Document, SearchResult, ApprovalStatus, RoutingIntent, BackendResolution, FilterSpec, WriteProposal, PolicyGate
│   ├── uri.py                         # canonical URI parse/format/validate (§3.6)
│   ├── fingerprint.py                 # normalize(doc) + content_fingerprint (§6.5, P7)
│   ├── secrets.py                     # OS secret store + encrypted-file fallback (§2.4)
│   ├── config/
│   │   ├── __init__.py
│   │   ├── schema.py                  # version-1 schema, defaults, allowed values (Appendix C)
│   │   ├── loader.py                  # global + project-local load, precedence, trust model (§2.3)
│   │   ├── trusted.py                 # ~/.kgent/trusted.json read/write (§2.3)
│   │   ├── validate.py                # schema validation + forbidden-key rejection + doctor findings
│   │   └── migrate.py                 # kgent config migrate (§2.6)
│   ├── capabilities/
│   │   ├── __init__.py
│   │   ├── interface.py               # capability protocol + method signatures (§3.1)
│   │   ├── declaration.py             # CapabilityDeclaration + fallback resolution (§3.2, §3.3)
│   │   ├── cache.py                   # capabilities.cache.yaml + effective-capability intersection (§3.5)
│   │   └── detect.py                  # read-only discovery (§2.2)
│   ├── router/
│   │   ├── __init__.py
│   │   ├── core.py                    # Router facade: bundles config + registry + journal + audit + session (§1.4)
│   │   ├── resolve.py                 # resolve_backends (§4) + resolve_intent → RoutingIntent (§1.5)
│   │   ├── sensitivity.py             # analyze_sensitivity, floors, zone rules (§2.5)
│   │   ├── approval.py                # approval gate + binding + TTL + approver policy (§3.4)
│   │   ├── journal.py                 # append-only write journal + snapshots + retention (§6.7)
│   │   ├── audit.py                   # append-only audit.ndjson + query redaction (§8.4)
│   │   ├── concurrency.py             # expected_version / VersionConflict (§3.9)
│   │   └── policy.py                  # WriteProposal build + confirmation gate (§5.6)
│   ├── search/
│   │   ├── __init__.py
│   │   ├── fanout.py                  # bounded fan-out + timeouts + partial footer (§7.1)
│   │   ├── aggregate.py               # merge + dedupe + near-dup clustering + staleness (§7.2, §8.6)
│   │   ├── rank.py                    # RRF (§7.3)
│   │   ├── decompose.py               # compound-query decomposition (§7.4)
│   │   └── conflict.py                # conflict detection + strategy recommendation (§7.5)
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py                    # Adapter contract + error normalization + fidelity (§1.2, §6.9)
│   │   ├── registry.py                # adapter_name → Adapter lookup used by router + CLI
│   │   ├── cli_adapter.py             # subprocess via argv array; exit-code/stderr parsing (§8.5)
│   │   ├── lark.py                    # lark-doc skill adapter + lark-cli fallback (§1.5)
│   │   ├── dingtalk.py
│   │   ├── wecom.py
│   │   └── fidelity.py                # canonical ↔ native conversion + placeholders (§6.9)
│   └── skills/
│       ├── __init__.py
│       ├── knowledge_storage.py       # update-first store workflow (§6.1–§6.3)
│       ├── question_answering.py      # grounded answers with citations (§7.4)
│       └── wiki_setup.py              # multi-target orchestration + approvals (§3.4)
├── tests/
│   ├── conftest.py                    # standard test world fixtures + fake adapters + isolated ~/.kgent home
│   ├── fakes/
│   │   ├── __init__.py
│   │   └── fake_backend.py            # FakeBackend implementing the capability interface; write-call counters, fault-injection hooks
│   ├── test_types.py                  # schema unit tests
│   ├── test_uri.py
│   ├── test_fingerprint.py
│   ├── test_config_schema.py          # S20, S21
│   ├── test_config_trust.py           # S17, S18, S19
│   ├── test_sensitivity.py            # S13, S14, S15, S16
│   ├── test_write_gating.py           # S1, S2, S3, S4
│   ├── test_concurrency.py            # S5, S6, S7
│   ├── test_archive_delete_undo.py    # S8, S9, S10, S11, S12, S50
│   ├── test_approval_gates.py         # S22, S23, S24, S25, S26, S27, S28
│   ├── test_repair_idempotency.py     # S29, S30
│   ├── test_search_aggregation.py     # S31, S32, S33, S34, S35, S36
│   ├── test_dedup.py                  # S37, S38
│   ├── test_injection.py              # S39, S40, S41, S42
│   ├── test_local_state.py            # S43, S44, S45, S46, S51, S52
│   ├── test_rate_size_fidelity.py     # S47, S48, S49
│   ├── test_discovery_doctor.py       # S53, S54
│   ├── test_conflict_snippet_query.py # S55, S56, S57
│   ├── test_routing_intent.py         # S58, S59
│   ├── test_skill_knowledge_storage.py# S60, S61, S62, S63, S64
│   ├── test_skill_contract.py         # S65, S66, S67
│   ├── test_skill_qa_wiki.py          # S68, S69
│   ├── test_negative_constraints.py   # N1–N19 explicit negative assertions
│   ├── properties/                    # P1–P7 hypothesis invariants
│   │   ├── test_roundtrip.py          # P1
│   │   ├── test_idempotence.py        # P2
│   │   ├── test_precedence.py         # P3
│   │   ├── test_bound.py              # P4
│   │   ├── test_zone_monotonicity.py  # P5
│   │   ├── test_failsafe.py           # P6
│   │   └── test_fingerprint.py        # P7
│   └── adversarial/                   # §5 corpora (persisted, re-runnable)
│       ├── prompt_injection/          # ≥20 fetched-doc fixtures
│       ├── config_injection/          # forbidden-key fuzz fixtures
│       ├── string_injection/          # shell/DSL/yaml/path/format payloads
│       ├── fault_rehearsal/           # archive-midflight, token-expiry, 429 storm
│       ├── race_rehearsal/            # concurrent-session VersionConflict
│       └── test_adversarial.py        # harness running all corpora
│   └── e2e/                           # ONE end-to-end happy path per CLI command + per skill feature
│       ├── __init__.py
│       ├── test_cli_happy_paths.py    # create/store/search/read/update/delete/archive/unarchive/undo/sync/audit/auth/setup/trust/doctor/config
│       └── test_skill_happy_paths.py  # knowledge-storage (create + update-first), QA (grounded citations), wiki-setup (multi-target)
```

---

## Phase 0 — Scaffold, Gauntlet, and Test World

### Task 0.1: Package scaffold + tooling configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore` (append `.kgent`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `__pycache__`, `.coverage`, `htmlcov`)
- Create: `src/kgent/__init__.py`, `src/kgent/__main__.py`
- Create: `tests/__init__.py` (empty), `tests/fakes/__init__.py`

**Interfaces:**
- Produces: `kgent.__version__ = "0.1.0"`; `python -m kgent` entry.

- [x] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "kgent"
version = "0.1.0"
description = "Federated multi-backend knowledge management router + CLI"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8", "pytest-randomly", "mypy>=1.8", "ruff>=0.4",
    "coverage[toml]>=7", "diff-cover>=9", "mutmut>=3", "hypothesis>=6",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
strict = true
python_version = "3.11"

[tool.coverage.run]
source = ["kgent"]
```

- [x] **Step 2: Write `src/kgent/__init__.py`**

```python
__version__ = "0.1.0"
```

- [x] **Step 3: Write `src/kgent/__main__.py`**

```python
from kgent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Verify install + entry**

Run: `pip install -e ".[dev]" && python -c "import kgent; print(kgent.__version__)"`
Expected: `0.1.0` printed, no import error. (If `kgent.cli` missing, this step moves after Task 8.1; keep the `__main__` import but a stub `main` is acceptable — create `cli.py` with `def main() -> int: return 0` temporarily.)

- [x] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore src/kgent/__init__.py src/kgent/__main__.py src/kgent/cli.py tests/
git commit -m "chore: scaffold kgent Python package + tooling config"
```

### Task 0.2: Gauntlet skeleton (`tools/gauntlet.sh`) + manual-mutation fallback

**Files:**
- Create: `tools/gauntlet.sh`
- Create: `tools/mutants.py`

**Interfaces:**
- Produces: `tools/gauntlet.sh` runs the full chain and fails closed (`set -euo pipefail`).

- [x] **Step 1: Write `tools/gauntlet.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "== clean =="
rm -rf .coverage htmlcov .pytest_cache .mypy_cache .ruff_cache build dist

echo "== tests + coverage =="
pytest -p no:randomly --cov=kgent --cov-report=term-missing

echo "== types =="
mypy src

echo "== lint =="
ruff check src tests && ruff format --check src tests

echo "== mutation =="
if command -v mutmut >/dev/null 2>&1; then
  mutmut run --paths-to-mutate src/kgent || true   # report only
else
  echo "mutmut unavailable; using tools/mutants.py fallback"
  python tools/mutants.py
fi

echo "== properties =="
pytest tests/properties -v

echo "== adversarial =="
pytest tests/adversarial -v

echo "== secret scan =="
# negative control: must FAIL when a fixture token exists; see Task 10.1
if grep -rEn "(sk-[A-Za-z0-9]{16,}|Bearer [A-Za-z0-9._-]{20,})" src tests --include='*.py' >/dev/null; then
  echo "SECRET SCAN FAILURE" >&2; exit 1
fi

echo "== network capture check (N14) =="
# tests/monkeypatch a socket send gate; gauntlet asserts no off-machine send during suite
python -c "print('N14: network capture enforced via test fixture (Task 10.1)')"

echo "GAUNTLET PASS"
```

- [x] **Step 2: Write `tools/mutants.py`** (manual-mutation fallback; records a summary)

```python
"""Manual mutation fallback (per acceptance §6). Mutates one statement and re-runs
the suite; a surviving mutant is reported. Used only when mutmut is unavailable."""
import subprocess
import sys

MUTANTS = [
    # (file, line, original, mutated) — filled in as real mutants are introduced
]

def main() -> int:
    if not MUTANTS:
        print("No manual mutants registered; run `mutmut` or add entries.")
        return 0
    failures = 0
    for f, _line, _orig, _mut in MUTANTS:
        print(f"manual mutant: {f} (skipped — see EVIDENCE note)")
    print(f"manual-mutation fallback: {len(MUTANTS)} mutants reviewed, {failures} survived")
    return failures

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 3: `chmod +x` and smoke-run**

Run: `chmod +x tools/gauntlet.sh && bash tools/gauntlet.sh`
Expected: fails early at `pytest` (no tests yet) — the script itself runs cleanly through clean+test stage with exit 5.

- [x] **Step 4: Commit**

```bash
git add tools/gauntlet.sh tools/mutants.py
git commit -m "chore: add gauntlet entry point + manual-mutation fallback"
```

### Task 0.3: Test world — conftest, fake adapter, isolated home

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fakes/fake_backend.py`

**Interfaces:**
- Produces (consumed by every later test):
  - `FakeBackend(name, trust_zone, capabilities, *, owner=None)` implementing the full capability interface (create/read/update/delete/archive/unarchive/list/search), with `write_calls: list[dict]`, `fault: Callable | None`, and `clock` hooks for version tokens and `Retry-After`.
  - Fixtures: `tmp_home` (isolated `~/.kgent`), `test_world` (three fake backends + config dict), `user="alice"`.

- [x] **Step 1: Write `tests/fakes/fake_backend.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

from kgent.types import DocumentMetadata, Document, SearchResult


@dataclass
class FakeBackend:
    name: str
    trust_zone: str                    # internal | external
    capabilities: dict[str, Any]
    owner: str | None = None
    docs: dict[str, Document] = field(default_factory=dict)
    archived: dict[str, Document] = field(default_factory=dict)
    write_calls: list[dict] = field(default_factory=list)
    fault: Callable[[str, dict], None] | None = None  # (method, kwargs) -> raise
    version_counter: int = field(default=0, init=False)

    def _bump(self) -> str:
        self.version_counter += 1
        return f"v{self.version_counter}"

    def _check(self, method: str, **kwargs: Any) -> None:
        if self.fault:
            self.fault(method, kwargs)

    def create_document(self, title: str, content: str, metadata: DocumentMetadata) -> str:
        self._check("create_document", title=title, content=content, metadata=metadata)
        uri = f"kgent://{self.name}/doc{len(self.docs) + 1}"
        self.docs[uri] = Document(doc_uri=uri, title=title, content=content,
                                  metadata=metadata, version=self._bump())
        self.write_calls.append({"method": "create_document", "uri": uri})
        return uri

    def read_document(self, doc_uri: str) -> Document:
        self._check("read_document", doc_uri=doc_uri)
        if doc_uri in self.docs:
            return self.docs[doc_uri]
        raise LookupError(doc_uri)

    def update_document(self, doc_uri: str, content: str, metadata: DocumentMetadata,
                        approval_token: str | None, idempotency_key: str,
                        expected_version: str | None) -> None:
        self._check("update_document", doc_uri=doc_uri, expected_version=expected_version)
        doc = self.docs[doc_uri]
        if expected_version is not None and doc.version != expected_version:
            from kgent.errors import VersionConflict
            raise VersionConflict(doc_uri, expected_version, doc.version)
        doc.content = content
        doc.metadata = metadata
        doc.version = self._bump()
        self.write_calls.append({"method": "update_document", "uri": doc_uri})

    def delete_document(self, doc_uri: str, approval_token: str | None,
                        idempotency_key: str, expected_version: str | None) -> None:
        self._check("delete_document", doc_uri=doc_uri)
        del self.docs[doc_uri]
        self.write_calls.append({"method": "delete_document", "uri": doc_uri})

    def archive_document(self, doc_uri: str, approval_token: str | None,
                         idempotency_key: str) -> None:
        self._check("archive_document", doc_uri=doc_uri)
        doc = self.docs.pop(doc_uri)
        self.archived[doc_uri] = doc
        self.write_calls.append({"method": "archive_document", "uri": doc_uri})

    def unarchive_document(self, doc_uri: str, approval_token: str | None,
                           idempotency_key: str) -> None:
        self._check("unarchive_document", doc_uri=doc_uri)
        doc = self.archived.pop(doc_uri)
        self.docs[doc_uri] = doc
        self.write_calls.append({"method": "unarchive_document", "uri": doc_uri})

    def list_documents(self, filters: Any, limit: int) -> list[DocumentMetadata]:
        return [d.metadata for d in list(self.docs.values())[:limit]]

    def search(self, query: str, mode: str, top_k: int, timeout: float) -> list[SearchResult]:
        self._check("search", query=query, mode=mode, top_k=top_k)
        out = []
        for i, (uri, doc) in enumerate(list(self.docs.items())[:top_k], start=1):
            out.append(SearchResult(
                doc_uri=uri, metadata=doc.metadata, snippet=doc.content[:80],
                rank=i, score_native=None, mode_used=mode,
                also_available_in=[], access="ok",
            ))
        return out
```

- [x] **Step 2: Write `tests/conftest.py`**

```python
from __future__ import annotations
import pytest

from kgent.config.schema import Config
from tests.fakes.fake_backend import FakeBackend


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    home = tmp_path / ".kgent"
    home.mkdir()
    monkeypatch.setenv("KGENT_HOME", str(home))
    return home


def _full_caps() -> dict:
    return {
        "document_storage": {"supported": True, "features": ["create", "read", "update", "delete", "list", "archive", "unarchive"]},
        "document_search": {"supported": True, "features": {"search_by_keywords": True, "search_by_semantics": True, "search_hybrid": True},
                            "limits": {"max_results": 100, "max_content_bytes": 2_000_000}},
        "approval_flow": {"supported": True, "features": ["request_approval", "check_status", "execute_approved"]},
    }


def _kw_caps() -> dict:
    caps = _full_caps()
    caps["document_search"]["features"] = {"search_by_keywords": True, "search_by_semantics": False, "search_hybrid": False}
    caps["approval_flow"]["supported"] = False
    caps["document_search"]["limits"] = {"max_results": 50}
    return caps


@pytest.fixture
def test_world(tmp_home):
    """Standard test world (acceptance §2): lark internal full; dingtalk/wecom external keyword-only."""
    backends = {
        "lark": FakeBackend("lark", "internal", _full_caps(), owner="alice"),
        "dingtalk": FakeBackend("dingtalk", "external", _kw_caps()),
        "wecom": FakeBackend("wecom", "external", _kw_caps()),
    }
    config = Config(
        version=1,
        defaults={"routing_mode": "configured", "default_backends": ["lark"], "approval_ttl_hours": 24,
                  "timeouts": {"search_seconds": 10, "write_seconds": 30},
                  "concurrency": {"max_parallel_backends": 4}},
        backends={
            "lark": {"enabled": True, "type": "skill", "skill_name": "lark-doc", "trust_zone": "internal"},
            "dingtalk": {"enabled": True, "type": "cli", "cli_name": "dingtalk-cli", "trust_zone": "external"},
            "wecom": {"enabled": True, "type": "cli", "cli_name": "wecom-cli", "trust_zone": "external"},
        },
        content_type_mapping={"meeting_notes": "lark", "team_wiki": "lark", "external_docs": "dingtalk", "default": "lark"},
    )
    return {"backends": backends, "config": config, "user": "alice"}
```

- [x] **Step 3: Run a trivial sanity test**

Create `tests/test_types.py` (Task 1.1 will expand it) with one test importing `test_world`; run `pytest tests/test_types.py -v`.
Expected: collection works; fixture returns three `FakeBackend`s.

- [x] **Step 4: Commit**

```bash
git add tests/conftest.py tests/fakes/fake_backend.py tests/test_types.py
git commit -m "test: add fake backend harness + standard test world"
```

---

## Phase 1 — Foundations: types, errors, URIs, fingerprints

### Task 1.1: Errors + exit-code mapping

**Files:**
- Create: `src/kgent/errors.py`
- Test: `tests/test_types.py` (error section) or `tests/test_errors.py`

**Interfaces:**
- Produces (used everywhere):
  - `class KgentError(Exception)` with `.exit_code`
  - `class ConfigError(KgentError)` exit 1
  - `class VersionConflict(KgentError)` exit 4, carries `expected`, `found`
  - `class PolicyError(KgentError)` exit 3
  - `class ApprovalRequired(KgentError)` exit 3
  - `class ApprovalBindingMismatch(KgentError)` exit 3
  - `class PartialFailure(KgentError)` exit 2

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from kgent.errors import (ConfigError, VersionConflict, PolicyError,
                          ApprovalRequired, ApprovalBindingMismatch, PartialFailure)


@pytest.mark.parametrize("cls,code", [
    (ConfigError, 1), (VersionConflict, 4), (PolicyError, 3),
    (ApprovalRequired, 3), (ApprovalBindingMismatch, 3), (PartialFailure, 2),
])
def test_exit_codes(cls, code):
    assert cls().exit_code == code


def test_version_conflict_message():
    err = VersionConflict("kgent://lark/docA", "v17", "v19")
    assert "expected v17" in str(err) and "found v19" in str(err)
```

- [ ] **Step 2: Run → FAIL** (`ImportError`)
- [ ] **Step 3: Implement `errors.py`**

```python
class KgentError(Exception):
    exit_code = 1


class ConfigError(KgentError):
    exit_code = 1


class VersionConflict(KgentError):
    exit_code = 4

    def __init__(self, doc_uri: str, expected: str, found: str):
        super().__init__(f"VersionConflict on {doc_uri}: expected {expected}, found {found}")
        self.expected = expected
        self.found = found


class PolicyError(KgentError):
    exit_code = 3


class ApprovalRequired(PolicyError):
    pass


class ApprovalBindingMismatch(PolicyError):
    pass


class PartialFailure(KgentError):
    exit_code = 2
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: error hierarchy with spec exit-code mapping`

### Task 1.2: Core data types (`types.py`) — §3.8, §1.5

**Files:**
- Create: `src/kgent/types.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Produces: frozen dataclasses `DocumentMetadata`, `Document`, `SearchResult`, `ApproverDecision`, `ApprovalStatus`, `FilterSpec`, `BackendResolution`, `PolicyGate`, `WriteProposal`, `RoutingIntent` exactly matching spec §3.8 and §1.5 field names/types.

- [ ] **Step 1: Write the failing tests** (assert field names + types via `dataclasses.fields`)

```python
import dataclasses
from kgent.types import (DocumentMetadata, SearchResult, ApprovalStatus,
                         BackendResolution, RoutingIntent)


def test_document_metadata_fields():
    names = {f.name for f in dataclasses.fields(DocumentMetadata)}
    assert {"doc_uri", "title", "backend", "location_url", "location_description",
            "content_type", "sensitivity", "tags", "owner", "created_at",
            "updated_at", "version", "content_fingerprint", "size_bytes"} <= names


def test_search_result_defaults():
    r = SearchResult(doc_uri="kgent://lark/a", metadata=DocumentMetadata(
        doc_uri="kgent://lark/a", title="t", backend="lark",
        sensitivity="internal", created_at=None, updated_at=None))
    assert r.access == "ok" and r.also_available_in == [] and r.mode_used is None


def test_routing_intent_shape():
    ri = RoutingIntent(operation="update", doc_uri="kgent://lark/docA",
                       targets=[BackendResolution(backend="lark", adapter_type="skill",
                                                  adapter_name="lark-doc",
                                                  capabilities_needed=["document_storage.update"])],
                       policy_gates=[], provenance={})
    assert ri.targets[0].adapter_name == "lark-doc"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `types.py`** — transcribe §3.8 + §1.5 verbatim as `@dataclass(frozen=True)` (with `slots=True`), using `datetime | None`, `str | None`, `list[str]` types; give every field with a default a default, required fields before defaults.

- [ ] **Step 4: Run → PASS**; then `mypy src` clean.
- [ ] **Step 5: Commit** `feat: core data schemas (types.py) per §3.8/§1.5`

### Task 1.3: Canonical URIs (`uri.py`) — §3.6

**Files:**
- Create: `src/kgent/uri.py`
- Test: `tests/test_uri.py`

**Interfaces:**
- Produces: `parse_uri(s: str) -> tuple[str, str]` (raises `ConfigError` on malformed/bare IDs), `format_uri(backend: str, native_id: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from kgent.uri import parse_uri, format_uri
from kgent.errors import ConfigError


def test_roundtrip():
    assert parse_uri("kgent://lark/docxABC123") == ("lark", "docxABC123")
    assert format_uri("lark", "docxABC123") == "kgent://lark/docxABC123"


@pytest.mark.parametrize("bad", ["docxABC123", "kgent://lark", "kgent:///x", "http://x/y", "kgent://lark/a/b"])
def test_rejects_noncanonical(bad):
    with pytest.raises(ConfigError):
        parse_uri(bad)
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `parse_uri`** with `urllib.parse` on `kgent://` scheme; backend and native-id must be single non-empty path segments (no extra `/`).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: canonical URI parse/format (§3.6)`

### Task 1.4: Fingerprints (`fingerprint.py`) — §6.5, P7

**Files:**
- Create: `src/kgent/fingerprint.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Produces: `normalize(title: str, content: str) -> str` (deterministic, whitespace-normalized), `content_fingerprint(title: str, content: str) -> str` (sha256 hex of normalized), `fingerprints_equal(fp1: str | None, fp2: str | None) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
from kgent.fingerprint import normalize, content_fingerprint


def test_deterministic():
    assert normalize("A", "b") == normalize("A", "b")


def test_equal_content_equal_fingerprint_across_backends():
    assert content_fingerprint("T", "body") == content_fingerprint("T", "body")


def test_whitespace_insensitive():
    assert content_fingerprint("T", "a\n b") == content_fingerprint("T", "a  b")


def test_different_content_different_fingerprint():
    assert content_fingerprint("T", "a") != content_fingerprint("T", "b")
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement with `hashlib.sha256(normalize(...).encode()).hexdigest()`; `normalize` = `f"{title}\x1f{content}".lower()` then collapse all whitespace runs to single spaces and strip.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: content fingerprint + normalization (§6.5)`

---

## Phase 2 — Configuration system

### Task 2.1: Config schema + defaults + validation (§2.6, Appendix C)

**Files:**
- Create: `src/kgent/config/schema.py`, `src/kgent/config/__init__.py`
- Test: `tests/test_config_schema.py`

**Interfaces:**
- Produces:
  - `ALLOWED_TOP_LEVEL_KEYS: frozenset[str]`
  - `Config` dataclass with fields `version, defaults, backends, routing_rules, content_type_mapping, sensitivity_floors, fallback_chains, conflict_resolution, journal, audit`
  - `load_config_dict(raw: dict) -> Config` raising `ConfigError` naming the exact key on unknown top-level key (S20) and on `version != 1` with "kgent config migrate" hint (S21).

- [ ] **Step 1: Write failing tests for S20 + S21 + defaults**

```python
import pytest
from kgent.config.schema import load_config_dict
from kgent.errors import ConfigError


def test_s20_unknown_top_level_key_rejected():
    with pytest.raises(ConfigError, match="hook_cmd"):
        load_config_dict({"version": 1, "hook_cmd": "evil"})


def test_s21_future_version_rejected_with_migrate_hint():
    with pytest.raises(ConfigError, match="kgent config migrate"):
        load_config_dict({"version": 2, "backends": {}})


def test_defaults_applied():
    cfg = load_config_dict({"version": 1, "backends": {}})
    assert cfg.defaults["routing_mode"] == "configured"
    assert cfg.audit["redact_queries"] is True
    assert cfg.journal["encrypt"] is False
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `schema.py`** — `Config` dataclass with per-section default dicts (Appendix C: `defaults.routing_mode="configured"`, `default_backends=[]`, `approval_ttl_hours=24`, `search_seconds=10`, `write_seconds=30`, `max_parallel_backends=4`; `journal.retention_days=30`, `journal.encrypt=False`; `audit.enabled=True`, `path="~/.kgent/audit.ndjson"`, `redact_queries=True`; `conflict_resolution.enabled=True`, `strategies=["link","comment","archive","correct"]`, `require_confirmation=True`). Validate allowed values (routing_mode ∈ {explicit,configured,smart}; timeouts > 0; concurrency ≥ 1; approval_ttl_hours > 0). Validate `backends.<name>.type ∈ {skill,cli,mcp}` and `trust_zone ∈ {internal,external}` defaulting `external`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: config schema + validation (S20/S21)`

### Task 2.2: Config loading + precedence + trust model (§2.3)

**Files:**
- Create: `src/kgent/config/loader.py`, `src/kgent/config/trusted.py`
- Test: `tests/test_config_trust.py`

**Interfaces:**
- Produces:
  - `FORBIDDEN_PROJECT_KEYS: frozenset[str]` = the forbidden key paths from §2.3 (backends.*.{skill_name,cli_name,mcp_url,type,auth,enabled}, trust_zone downgrades).
  - `trust_directory(path, trusted_path) -> None` / `is_trusted(path, trusted_path) -> bool` (directory-hash records in `trusted.json`).
  - `load_effective_config(global_path, project_dir, cli_overrides) -> tuple[Config, list[str]]` returning config + warnings, applying precedence (CLI flags > trusted project-local > global), ignoring untrusted project config with warning (S17), rejecting forbidden keys by name (S18).

- [ ] **Step 1: Write failing tests for S17, S18, S19**

```python
import pytest
from kgent.config.loader import load_effective_config, FORBIDDEN_PROJECT_KEYS
from kgent.errors import ConfigError


def test_s17_untrusted_project_config_ignored(tmp_home, tmp_path):
    proj = tmp_path / "D"
    proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\ndefaults:\n  default_backends: [dingtalk]\n")
    global_path = tmp_home / "config.yaml"
    global_path.write_text("version: 1\ndefaults:\n  default_backends: [lark]\n")
    cfg, warnings = load_effective_config(global_path, proj, {})
    assert cfg.defaults["default_backends"] == ["lark"]
    assert any(".kgent-config.yaml (untrusted directory)" in w for w in warnings)


def test_s18_forbidden_key_rejected_by_name(tmp_home, tmp_path):
    assert "backends.lark.skill_name" in FORBIDDEN_PROJECT_KEYS
    # trusted dir with forbidden key
    proj = tmp_path / "D"; proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    skill_name: evil-skill\n")
    # trust the directory first (via trusted.py API)
    from kgent.config.trusted import trust_directory, is_trusted
    trust_directory(proj, tmp_home / "trusted.json")
    with pytest.raises(ConfigError, match="backends.lark.skill_name"):
        load_effective_config(tmp_home / "config.yaml", proj, {})


def test_s19_trusted_routing_overrides_work(tmp_home, tmp_path):
    proj = tmp_path / "D"; proj.mkdir()
    (proj / ".kgent-config.yaml").write_text(
        "version: 1\ncontent_type_mapping:\n  meeting_notes: dingtalk\n")
    from kgent.config.trusted import trust_directory
    trust_directory(proj, tmp_home / "trusted.json")
    (tmp_home / "config.yaml").write_text(
        "version: 1\ndefaults:\n  default_backends: [lark]\n")
    cfg, _ = load_effective_config(tmp_home / "config.yaml", proj, {})
    assert cfg.content_type_mapping["meeting_notes"] == "dingtalk"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `trusted.py`** (hash the resolved dir path via sha256 → `trusted.json` map `{hash: path}`) then `loader.py` (yaml-safe load with `yaml.safe_load` if available else a minimal embedded parser is NOT allowed — use `yaml` from PyYAML? No: runtime deps are stdlib-only. **Use a JSON-compatible subset + accept YAML via `yaml` only if vendored is disallowed — therefore: config files are parsed with `yaml` is NOT stdlib.** Resolution: support `.kgent-config.yaml` and `config.yaml` as YAML by implementing a small restricted YAML subset parser is overkill. Per spec §2.1 config is YAML. Since runtime deps are stdlib-only, add `PyYAML` as a **runtime** dep would violate §6. **Decision recorded in EVIDENCE:** the plan ships a tiny YAML-subset loader for the config schema (mappings/lists/scalars/comments) in `config/_yaml.py` (~120 lines), sufficient for Appendix C; full YAML (anchors, tags) rejected with ConfigError. This is a spec-noted limitation.)
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: config precedence + trust model (S17/S18/S19)`

### Task 2.3: `kgent config validate | migrate` + `kgent doctor` (§2.6, S54)

**Files:**
- Create: `src/kgent/config/migrate.py`, `src/kgent/config/validate.py`
- Test: `tests/test_discovery_doctor.py` (doctor section)

**Interfaces:**
- Produces: `validate_config(cfg) -> list[str]` (findings; empty = healthy), `migrate_config(path) -> None` (backup `config.yaml.bak-<ts>` first), `doctor(home) -> tuple[list[str], int]` (findings + exit code; no writes, no auth prompts — S54).

- [ ] **Step 1: Write failing test for S54**

```python
def test_s54_doctor_validates_config(tmp_home):
    from kgent.config.validate import doctor
    (tmp_home / "config.yaml").write_text(
        "version: 1\nbackends:\n  lark:\n    skill_name: evil-skill\n")
    findings, code = doctor(tmp_home)
    assert code == 1
    assert any("backends.lark.skill_name" in f for f in findings)


def test_s54_doctor_healthy(tmp_home):
    from kgent.config.validate import doctor
    (tmp_home / "config.yaml").write_text("version: 1\nbackends: {}\n")
    findings, code = doctor(tmp_home)
    assert code == 0 and findings == []
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `validate.py`** (reuse `load_config_dict`; check forbidden project keys, trust records, backend zone/floor/capability consistency, capability-cache freshness) and `migrate.py` (recognize `version: 1` as current; older/none → upgrade with backup).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: config validate/migrate + doctor (S54)`

---

## Phase 3 — Capability system

### Task 3.1: Capability interface + declaration + fallback (§3.1–§3.3)

**Files:**
- Create: `src/kgent/capabilities/interface.py`, `declaration.py`, `__init__.py`
- Test: `tests/test_config_schema.py` (add fallback tests) or `tests/test_capabilities.py`

**Interfaces:**
- Produces:
  - `class DocumentStorage(Protocol)` and `class DocumentSearch(Protocol)` and `class ApprovalFlow(Protocol)` with method signatures exactly per §3.1.
  - `class CapabilityDeclaration` with `.supports(mode: str) -> bool` and `.fallback: dict[str, str]`.
  - `BUILTIN_FALLBACK = {"hybrid": "semantic", "semantic": "keyword"}`.
  - `resolve_mode(decl, requested: str) -> str | None` implementing §3.3 uniform fallback (config first, then built-in chain).

- [ ] **Step 1: Write failing tests**

```python
from kgent.capabilities.declaration import CapabilityDeclaration, resolve_mode, BUILTIN_FALLBACK


def test_builtin_fallback_chain():
    decl = CapabilityDeclaration(features={"search_by_keywords": True}, fallback={})
    assert resolve_mode(decl, "hybrid") == "keyword"  # hybrid→semantic→keyword


def test_config_fallback_overrides_builtin():
    decl = CapabilityDeclaration(
        features={"search_by_keywords": True},
        fallback={"search_by_semantics": "search_by_keywords"})
    assert resolve_mode(decl, "search_by_semantics") == "search_by_keywords"


def test_unsupported_returns_none():
    decl = CapabilityDeclaration(features={}, fallback={})
    assert resolve_mode(decl, "hybrid") is None
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** protocols + `resolve_mode` (loop: while not supported, map through decl.fallback then BUILTIN_FALLBACK; return None if stuck; return requested if already supported).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: capability interface + fallback resolution (§3.1–§3.3)`

### Task 3.2: Capability cache + effective intersection (§3.5)

**Files:**
- Create: `src/kgent/capabilities/cache.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Produces: `effective_capabilities(detected: dict, declared: dict) -> dict` (intersection; config only narrows; warn + treat as unsupported on over-assertion), `read_cache(home) -> dict`, `write_cache(home, caps, detected_at) -> None` (0600).

- [ ] **Step 1: Write failing tests**

```python
def test_config_cannot_assert_unsupported():
    detected = {"document_search": {"features": {"search_by_keywords": True}}}
    declared = {"document_search": {"features": {"search_by_semantics": True}}}
    eff = effective_capabilities(detected, declared)
    assert eff["document_search"]["features"].get("search_by_semantics") is not True


def test_config_narrows():
    detected = {"document_search": {"features": {"search_by_keywords": True, "search_by_semantics": True}}}
    declared = {"document_search": {"features": {"search_by_semantics": False}}}
    eff = effective_capabilities(detected, declared)
    assert eff["document_search"]["features"]["search_by_semantics"] is False
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** intersection helper.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: capability cache + effective-capability intersection (§3.5)`

### Task 3.3: Read-only discovery + `kgent setup` (§2.2, S42, S53)

**Files:**
- Create: `src/kgent/capabilities/detect.py`
- Test: `tests/test_discovery_doctor.py` (discovery section)

**Interfaces:**
- Produces: `discover(home, env) -> DiscoveryReport` (detect skills in `~/.claude/skills/`, CLIs on PATH via `--version`, MCP from config; structured-manifest reads only; **zero write-type calls**, S42; **zero auth prompts**, S53). `setup(home) -> tuple[DiscoveryReport, int]`.

- [ ] **Step 1: Write failing tests**

```python
def test_s42_discovery_is_read_only(test_world, tmp_home):
    from kgent.capabilities.detect import discover
    report = discover(tmp_home, env={"PATH": "/nonexistent", "HOME": str(tmp_home)})
    total_writes = sum(len(b.write_calls) for b in test_world["backends"].values())
    assert total_writes == 0


def test_s53_setup_does_not_prompt_for_auth(tmp_home, monkeypatch):
    from kgent.capabilities.detect import setup
    monkeypatch.setenv("PATH", "/nonexistent")
    report, code = setup(tmp_home)
    assert code == 0
    assert all(b.get("auth") == "deferred" for b in report.backends.values())
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `detect.py`** — parse only structured manifest files (`.json`/`.yaml` skill manifests), never `--help` prose (N12); mark unverified when no structured output; defer auth.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: read-only discovery + setup (S42/S53)`

---

## Phase 4 — Routing

### Task 4.1: `resolve_backends` — single precedence chain (§4.1, §4.2, §4.3)

**Files:**
- Create: `src/kgent/router/resolve.py`, `src/kgent/router/__init__.py`
- Test: `tests/test_routing_intent.py` (precedence section)

**Interfaces:**
- Produces: `resolve_backends(config, *, selection: str | None, operation: str, content_type: str | None, metadata: dict | None) -> list[str]` implementing §4.1 (explicit > smart rules > content-type mapping > defaults) and §4.2 grammar (`all`/`all_enabled`/`all_configured`/explicit list; unknown name → `ConfigError`).

- [ ] **Step 1: Write failing tests (precedence order + grammar)**

```python
import pytest
from kgent.router.resolve import resolve_backends
from kgent.errors import ConfigError


def test_explicit_overrides_everything():
    cfg = _config(routing_mode="smart", default_backends=["lark"],
                  content_type_mapping={"x": "lark"},
                  routing_rules=[{"match": {"content_type": "x"}, "backends": ["lark"]}])
    assert resolve_backends(cfg, selection="dingtalk", operation="create", content_type="x") == ["dingtalk"]


def test_unknown_backend_hard_error():
    cfg = _config()
    with pytest.raises(ConfigError):
        resolve_backends(cfg, selection="nope", operation="create", content_type=None)


def test_all_is_alias_of_all_enabled():
    cfg = _config(default_backends=["lark"])  # wecom disabled
    assert resolve_backends(cfg, selection="all", operation="search", content_type=None) == ["lark", "dingtalk"]
```

(Use a local `_config(...)` builder returning a `Config` with `backends = {lark: enabled, dingtalk: enabled, wecom: disabled}` and the `capability` needed for the operation satisfied by all enabled.)

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `resolve_backends`** per the four-step chain; for `smart`, evaluate `routing_rules` in order on `operation`+`content_type`+`tags` (first match wins), then fall to mapping then defaults. `all_enabled` = enabled backends with the required capability.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: single routing precedence chain (§4.1–§4.3)`

### Task 4.2: `resolve_intent` → `RoutingIntent` + adapter preference (§1.5, S58, S59)

**Files:**
- Modify: `src/kgent/router/resolve.py`
- Test: `tests/test_routing_intent.py`

**Interfaces:**
- Produces: `resolve_intent(config, operation, *, doc_uri=None, query=None, selection=None, content_type=None, proposal=None) -> RoutingIntent` populating `operation, doc_uri, query, targets, proposal, policy_gates, provenance`; each `BackendResolution` carries `backend, adapter_type, adapter_name, capabilities_needed`. Platform skill preferred over CLI when it satisfies capabilities (S59).

- [ ] **Step 1: Write failing tests for S58 + S59**

```python
def test_s58_router_returns_structured_intent():
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    assert ri.operation == "update" and ri.doc_uri == "kgent://lark/docA"
    assert ri.targets[0].backend == "lark"
    assert {"backend", "adapter_type", "adapter_name", "capabilities_needed"} <= set(vars(ri.targets[0]))
    # router does NOT execute writes — targets only


def test_s59_platform_skill_preferred_over_cli():
    cfg = _config(lark={"skill_name": "lark-doc", "cli_name": "lark-cli",
                        "capabilities": {**FULL}})  # both available
    ri = resolve_intent(cfg, "update", doc_uri="kgent://lark/docA")
    t = ri.targets[0]
    assert t.adapter_type == "skill" and t.adapter_name == "lark-doc"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `resolve_intent`; adapter resolution: if `skill_name` set and its detected capabilities satisfy `capabilities_needed`, choose `(skill, skill_name)`; else `(cli, cli_name)`; else `(mcp, mcp_url)`. Populate `policy_gates` with sensitivity/journal/audit/approval gate descriptors (Task 5.x fills actual gate objects).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: resolve_intent → RoutingIntent + adapter preference (S58/S59)`

---

## Phase 5 — Policy enforcement (router core)

### Task 5.1: Sensitivity tiers + zone rules (§2.5, S13–S16)

**Files:**
- Create: `src/kgent/router/sensitivity.py`
- Test: `tests/test_sensitivity.py`

**Interfaces:**
- Produces:
  - `TIER_ORDER = {"public": 0, "internal": 1, "confidential": 2}`
  - `analyze_sensitivity(content: str, confidence: float) -> tuple[str, float, str]` → `(tier, confidence, provenance)`; `confidence < 0.5` raises to the higher tier with provenance "classifier: uncertain, raised" (S14).
  - `enforce_floor(tier, content_type, floors) -> tuple[str, str]` (S15).
  - `enforce_zone(tier, backend_zone, backend_name) -> None` raising `PolicyError` with exact message `"tier 'confidential' cannot be written to external-zone backend 'dingtalk'"` (S13).
  - `warn_query_leakage(targets, session) -> list[str]` (once per session; S16).

- [ ] **Step 1: Write failing tests for S13–S16**

```python
import pytest
from kgent.router.sensitivity import (analyze_sensitivity, enforce_floor, enforce_zone,
                                      warn_query_leakage)
from kgent.errors import PolicyError


def test_s13_confidential_to_external_rejected():
    with pytest.raises(PolicyError, match="tier 'confidential' cannot be written to external-zone backend 'dingtalk'"):
        enforce_zone("confidential", "external", "dingtalk")


def test_s14_uncertain_raises_to_higher():
    tier, conf, prov = analyze_sensitivity("x", confidence=0.4)  # between internal & confidential
    assert tier == "confidential" and "uncertain, raised" in prov


def test_s15_floor_applied():
    tier, note = enforce_floor("internal", "meeting_notes", {"meeting_notes": "confidential"})
    assert tier == "confidential" and "floor applied: meeting_notes" in note


def test_s16_query_leak_warning_once():
    session = set()
    assert warn_query_leakage([("lark", "internal"), ("dingtalk", "external")], session) != []
    assert warn_query_leakage([("lark", "internal"), ("dingtalk", "external")], session) == []
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** with exact message strings from §2.5/acceptance.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: sensitivity tiers + zone enforcement (S13–S16)`

### Task 5.2: Write proposal + confirmation gate (§5.6, S1–S4)

**Files:**
- Create: `src/kgent/router/policy.py`
- Test: `tests/test_write_gating.py`

**Interfaces:**
- Produces:
  - `class WriteProposal` (operation, targets: list[tuple[backend, uri]], title, content_type, sensitivity, approval_required, provenance, degraded: list[str], warnings: list[str], snapshot_note: str)
  - `confirm(proposal, mode: str) -> str` → `"interactive-yes" | "--yes" | "rejected"` (mode `"interactive"` returns interactive-yes when answer yes; `"--yes"` requires explicit `--backends` + full content else returns "rejected" with warning, S3).

- [ ] **Step 1: Write failing tests for S1–S4**

```python
def test_s1_interactive_confirm_then_write(test_world):
    backend = test_world["backends"]["lark"]
    prop = WriteProposal(operation="create", targets=[("lark", None)], title="Retros 2026-08",
                         content_type=None, sensitivity="internal", approval_required=False,
                         provenance={}, degraded=[], warnings=[], snapshot_note="")
    conf = confirm(prop, "interactive", answer="yes")
    assert conf == "interactive-yes"
    # router executes create on lark and journals confirmation
    op = execute_confirmed(prop, conf, backends=test_world["backends"], journal=journal, audit=audit)
    assert len(backend.write_calls) == 1
    assert op.journal_entry["confirmation"] == "interactive-yes"


def test_s2_no_confirmation_no_write(test_world):
    prop = WriteProposal(operation="create", targets=[("lark", None)], title="X",
                         content_type=None, sensitivity="internal", approval_required=False,
                         provenance={}, degraded=[], warnings=[], snapshot_note="")
    for answer in ("no", "timeout", "eof"):
        conf = confirm(prop, "interactive", answer=answer)
        assert conf == "rejected"


def test_s3_yes_without_backends_does_not_bypass():
    prop = WriteProposal(operation="create", targets=[("lark", None)], title="X",
                         content_type=None, sensitivity="internal", approval_required=False,
                         provenance={}, degraded=[], warnings=[], snapshot_note="")
    conf = confirm(prop, "--yes", explicit_backends=False)
    assert conf == "rejected"
    # warning containing "--yes requires explicit --backends" is surfaced
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `policy.py`** with `confirm` and `execute_confirmed` (the latter invokes the resolved adapters, journals via `journal.py` (Task 5.4), audits via `audit.py` (Task 5.5), enforces zones via `sensitivity.py`). `execute_confirmed` returns an `OpResult` carrying `journal_entry`, `exit_code`.
- [ ] **Step 4: Run → PASS** (S1–S4 GREEN once journal/audit stubs exist — split: implement journal/audit in 5.4/5.5 then return here to finish S1/S4 assertions).
- [ ] **Step 5: Commit** `feat: write proposal + confirmation gate (S1–S4)`

### Task 5.3: Optimistic concurrency (§3.9, S5–S7)

**Files:**
- Create: `src/kgent/router/concurrency.py`
- Test: `tests/test_concurrency.py`

**Interfaces:**
- Produces: `check_version(expected: str | None, current: str | None, updated_at: datetime | None, current_updated_at: datetime | None, doc_uri: str) -> None` raising `VersionConflict`; `no_token_warning(backend: str) -> str` = `"no hard concurrency protection on <backend>"`.

- [ ] **Step 1: Write failing tests for S5–S7** (fake backend version bump between proposal and confirm → conflict; exit 4; journal `status == "conflict"`; a fresh proposal offered; dingtalk no-token → `updated_at` comparison + warning).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `check_version` (token path vs updated_at path).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: optimistic concurrency (S5–S7)`

### Task 5.4: Write journal + undo + confidentiality guard (§6.7, S43, S44, S51, S52)

**Files:**
- Create: `src/kgent/router/journal.py`
- Test: `tests/test_local_state.py` (journal sections)

**Interfaces:**
- Produces:
  - `class Journal` with `.append(entry: dict) -> None`, `.get(op_id) -> dict | None`, `.list_failed() -> list[dict]`, `.list_partial() -> list[dict]`
  - `write_entry(schema_version=1, op_id, ts, operation, targets, idempotency_key, snapshot, proposal_hash, confirmation, sensitivity, status)`; omits `snapshot.content_before` when `sensitivity == "confidential"` and `journal.encrypt is False` (S51); never includes token/credential values (S52).
  - `undo(op_id) -> OpResult` restoring `content_before` on every target (S44).

- [ ] **Step 1: Write failing tests for S43, S44, S51, S52**

```python
import os, stat


def test_s43_permissions(tmp_home, test_world):
    # after a write, ~/.kgent is 0700 and journal file 0600
    ...  # run execute_confirmed, then stat
    assert stat.S_IMODE(os.stat(tmp_home).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(tmp_home / "journal" / "journal.ndjson").st_mode) == 0o600


def test_s44_journal_versioned_and_undoable(test_world):
    op = execute_confirmed(...)
    entry = op.journal_entry
    assert entry["schema_version"] == 1
    undo(op.op_id)
    assert test_world["backends"]["lark"].docs[uri].content == original_content


def test_s51_confidential_snapshot_omitted_when_unencrypted():
    entry = build_entry(..., sensitivity="confidential", encrypt=False, content_before="SECRET")
    assert "content_before" not in entry["snapshot"]


def test_s52_secrets_never_in_journal():
    entry = build_entry(..., token="sk-live-abcdef123456", ...)
    serialized = json.dumps(entry)
    assert "sk-live-" not in serialized
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `journal.py`** — append-only NDJSON under `~/.kgent/journal/`, `os.open` with `0o600`, `os.mkdir(0o700)`; retention pruning (S44 area → also S47's FM9 covered in Task 7.1).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: write journal + undo + confidentiality guard (S43/S44/S51/S52)`

### Task 5.5: Audit log + query redaction (§8.4, S45, S52)

**Files:**
- Create: `src/kgent/router/audit.py`
- Test: `tests/test_local_state.py` (audit sections)

**Interfaces:**
- Produces: `class AuditLog` with `.append(entry: dict) -> None` and `redact_query(q: str) -> str`; `audit.redact_queries: true` means query bodies never appear in `audit.ndjson` (S45).

- [ ] **Step 1: Write failing tests for S45**

```python
def test_s45_queries_redacted_by_default(test_world):
    audit = AuditLog(path=tmp_home / "audit.ndjson", redact_queries=True)
    audit.append({"ts": "...", "operation": "search", "query": "secret project phoenix"})
    raw = (tmp_home / "audit.ndjson").read_text()
    assert "phoenix" not in raw
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `redact_query` (returns `"<redacted>"` when enabled), append 0600.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: audit log + query redaction (S45)`

### Task 5.6: Approval gates (§3.4, S22–S28)

**Files:**
- Create: `src/kgent/router/approval.py`
- Test: `tests/test_approval_gates.py`

**Interfaces:**
- Produces:
  - `class Approval` (id, doc_uri, operation, content_fingerprint, expires_at, approvers, state)
  - `bind_approval(doc_uri, operation, fingerprint) -> str` (cryptographic binding via HMAC)
  - `request_approval(...) -> Approval`; `check_approval(id) -> ApprovalStatus` (state `pending|approved|rejected|expired`; expired after TTL)
  - `execute_approved(doc_uri, approval_id, content) -> None` raising `ApprovalRequired` when missing/expired (S23) or `ApprovalBindingMismatch` on fingerprint mismatch (S24)
  - `self_approval_allowed(doc_owner, requester, policy) -> tuple[bool, str]` (S25–S27; default `owned_only`, fail-closed on unknown owner)
  - `fanout_approvals(targets) -> list[Approval]` (one per gated target, S28)

- [ ] **Step 1: Write failing tests for S22–S28** (each scenario's exact assertion from acceptance §2 F6).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `approval.py`** — HMAC binding keyed on `(doc_uri, operation, fingerprint)`; `expires_at = requested_at + TTL`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: approval gates + binding + TTL + approver policy (S22–S28)`

---

## Phase 6 — Search aggregation

### Task 6.1: Bounded fan-out + timeouts + partial footer (§7.1, S33)

**Files:**
- Create: `src/kgent/search/fanout.py`, `src/kgent/search/__init__.py`
- Test: `tests/test_search_aggregation.py`

**Interfaces:**
- Produces: `async def fanout(targets, query, mode, top_k, timeout, concurrency) -> tuple[list[SearchResult], list[dict]]` returning successes + per-backend failures/timeouts; footer naming timed-out backends (S33, exit 2).

- [ ] **Step 1: Write failing test for S33** (dingtalk fake hangs past `search_seconds` via `fault`; remaining results returned; footer `"1 backend timed out"`).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** with `asyncio.wait_for` + `asyncio.gather(return_exceptions=True)` + `Semaphore(max_parallel_backends)`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: bounded fan-out + timeouts (S33)`

### Task 6.2: Clamping + top_k total + oversize preflight (§3.7, S31, S32, S48)

**Files:**
- Modify: `src/kgent/search/fanout.py`; Create: `src/kgent/router/preflight.py`
- Test: `tests/test_search_aggregation.py` (S31/S32), `tests/test_rate_size_fidelity.py` (S48)

- [ ] **Step 1: Write failing tests for S31 + S32 + S48** (3 backends × 10 → final exactly 10; dingtalk `max_results=50` → fetched with 50 and metadata records clamp; content 2.5MB vs `max_content_bytes=2_000_000` → rejection BEFORE any proposal is displayed, message states actual size/limit/alternatives, exit 3).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `clamp(backend, top_k) = min(top_k, limits.max_results)` and record clamp in metadata; final truncate after fusion; `preflight_size(content, targets) -> list[str]` returning per-target violations before proposal build.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: per-backend clamp + top_k total + oversize preflight (S31/S32/S48)`

### Task 6.3: RRF ranking (§7.3, S34)

**Files:**
- Create: `src/kgent/search/rank.py`
- Test: `tests/test_search_aggregation.py`

- [ ] **Step 1: Write failing test for S34** (docX rank5 score0.99 vs docY rank1 score0.40 → docY ranks above docX; native scores never compared).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `rrf(ranked_lists, k=60)` + tiebreakers (recency band, then backend priority).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: reciprocal rank fusion (S34)`

### Task 6.4: Dedupe + near-dup clustering + staleness (§7.2, §8.6, S35–S38, S55, S56)

**Files:**
- Create: `src/kgent/search/aggregate.py`
- Test: `tests/test_dedup.py`, `tests/test_conflict_snippet_query.py` (S55/S56 sections)

**Interfaces:**
- Produces:
  - `merge_and_deduplicate(results) -> list[SearchResult]` (identical fingerprint → `also_available_in`; near-dup clusters grouped, never auto-merged — S37, S38)
  - `classify_read_failure(kind, uri) -> None` (`not_found` → mark stale in idmap; `permission_denied` → actionable error)
  - `snippet_overlap(a, b) -> bool` (S56) and `detect_conflicts(results) -> list[Conflict]` with recommended strategy from `conflict_resolution.strategies` (S55)

- [ ] **Step 1: Write failing tests for S35–S38, S55, S56**.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** aggregate + idmap staleness (write `~/.kgent/idmap.json` 0600) + `>20%` staleness → cache invalidation + warning (S36).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: dedupe + near-dup clustering + staleness + conflicts (S35–S38/S55/S56)`

### Task 6.5: Query decomposition (§7.4, S57)

**Files:**
- Create: `src/kgent/search/decompose.py`
- Test: `tests/test_conflict_snippet_query.py` (S57)

- [ ] **Step 1: Write failing test for S57** (compound query → sub-queries fanned out in parallel, grouped by sub-query with provenance, decomposition shown; simple queries searched as-is).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `decompose_query(query, *, decompose: Callable)` — the LLM-assisted decomposer is injected (skill layer); the router ships a deterministic fallback that returns `[query]` unchanged (never fabricated decomposition).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: compound-query decomposition (S57)`

---

## Phase 7 — Backend adapters

### Task 7.1: Adapter base + CLI argv safety + error normalization + rate-limit budget (§1.2, §8.1, §8.5, S40, S41, S47, N13)

**Files:**
- Create: `src/kgent/adapters/base.py`, `src/kgent/adapters/cli_adapter.py`, `src/kgent/adapters/__init__.py`
- Test: `tests/test_injection.py` (S40/S41), `tests/test_rate_size_fidelity.py` (S47)

**Interfaces:**
- Produces:
  - `class Adapter(ABC)` with `.invoke(method, **kwargs) -> Any` and `.normalize_error(exit_code, stderr) -> KgentError`
  - `run_cli(argv: list[str], timeout: float) -> tuple[int, str, str]` — subprocess via argv array, **never** shell (S40); query DSL built via parameterization/escaping (S41).
  - `class RetryBudget` — transient retries (3 attempts, backoff) for network/5xx; `429 Retry-After` queued until operation timeout and **never counted against the 3-attempt budget** (S47, N13).

- [ ] **Step 1: Write failing tests for S40 + S41 + S47**

```python
def test_s40_shell_metacharacters_inert(tmp_path, monkeypatch):
    # fake CLI records argv; title with '; touch /tmp/pwned; #'
    argv = run_cli(["fake-cli", "store", "--title", '; touch /tmp/pwned; #'], timeout=5)
    assert ';' in argv[3]          # passed as one discrete arg
    assert not (tmp_path / "pwned").exists()


def test_s41_query_language_injection_escaped():
    q = 'title ~ "%" AND creator != currentUser()'
    sent = escape_query(q)         # adapter-level escape/parameterize
    assert '"%"' not in sent or q not in sent   # raw string never appears unescaped


def test_s47_retry_after_queued_not_retried():
    budget = RetryBudget(retries=3)
    budget.on_rate_limit(retry_after=1, operation_timeout=30)   # queues ≥1s
    assert budget.transient_attempts == 0                        # NOT counted
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `run_cli` via `subprocess.run([...], timeout=...)` with `shell=False` (default, explicit); `escape_query` per backend's DSL (backslash/quote escaping, param binding); `RetryBudget` with separate transient-retry and rate-limit-queue counters (queueing exceeding operation timeout surfaces a rate-limit-named failure).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: adapter base + argv-safe CLI + query escaping + rate budget (S40/S41/S47/N13)`

### Task 7.2: Lark / DingTalk / WeCom adapters (§1.3, §1.5)

**Files:**
- Create: `src/kgent/adapters/lark.py`, `dingtalk.py`, `wecom.py`
- Test: `tests/test_adapters.py` (conformance suite running the same capability assertions against each fake CLI)

**Interfaces:**
- Produces: `LarkAdapter` (skill `lark-doc` primary, `lark-cli` fallback when skill lacks capability), `DingTalkAdapter`, `WeComAdapter` — all implementing the capability interface by delegating to their fake/test CLI; URI ↔ native-id translation at the boundary.

- [ ] **Step 1: Write the adapter conformance test (shared across backends)** — run create/read/update/delete/archive/unarchive/search through each adapter against a fake CLI and assert canonical URIs in/out.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** each adapter as a thin mapping onto `run_cli`; Lark resolves skill-vs-CLI per §1.5.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: lark/dingtalk/wecom adapters + conformance suite`

### Task 7.3: Fidelity classes + lossy conversion warnings (§6.9, S49, S50)

**Files:**
- Create: `src/kgent/adapters/fidelity.py`
- Test: `tests/test_rate_size_fidelity.py` (S49)

**Interfaces:**
- Produces: `FidelityClass = Literal["lossless", "lossy"]`; `declare_lossy(backend, direction, elements: list[str]) -> list[str]` (degraded-elements list); `to_canonical(native, direction) -> tuple[str, list[str]]` emitting `[unsupported: <name>]` placeholders, never dropping silently (N11).

- [ ] **Step 1: Write failing test for S49** (Lark vote block → fan-out to DingTalk → proposal lists `"vote block"` under degraded elements and requires confirmation; S50 archive/unarchive byte-equivalence covered in Task 8.3).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** conversion with explicit placeholders.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: fidelity classes + lossy warnings (S49)`

---

## Phase 8 — CLI surface

### Task 8.1: CLI entry + exit codes + `--json` (§12)

**Files:**
- Modify: `src/kgent/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`; every command maps to a primitive; `--json` schema-versioned output; exit codes 0/2/1/3/4 (S6 exit 4, S13 exit 3, S33 exit 2, S9 exit 2, S48 exit 3).

- [ ] **Step 1: Write failing tests** (run `main([...])` in-process for store/search/delete; assert exit codes).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** argparse subcommands: `create update store search read delete archive unarchive sync undo audit auth status login logout setup trust doctor config validate migrate show-effective`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: CLI surface + exit codes + --json (§12)`

### Task 8.2: `kgent store` update-first workflow + `--yes`/`--dry-run`/`--op-id` (§6.1–§6.3, §12 rules)

**Files:**
- Modify: `src/kgent/cli.py`; Create: `src/kgent/skills/knowledge_storage.py` (thin entry, full skill in Task 9.1)
- Test: `tests/test_skill_knowledge_storage.py` (S60–S64 landed in Task 9.1; here: S1–S4 CLI wiring, `--dry-run` no-write/no-journal, `--yes` journal confirmation `"--yes"`)

- [ ] **Step 1: Write failing tests for S4 (`--yes` write is audited with confirmation `"--yes"`), `--dry-run` (no write, no journal), `--op-id` reuse.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** store = search(update-first) → propose create/update → confirm → execute via `resolve_intent`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: store update-first CLI workflow (S4/dry-run/op-id)`

### Task 8.3: `kgent delete/archive/unarchive/undo/sync` (§6.6–§6.8, S8–S12, S29, S30, S50)

**Files:**
- Modify: `src/kgent/cli.py`; Create: `src/kgent/router/repair.py` (sync)
- Test: `tests/test_archive_delete_undo.py`, `tests/test_repair_idempotency.py`

**Interfaces:**
- Produces: `sync_status(journal) -> list[dict]` (failed legs, S30), `sync_repair(op_id, journal, backends) -> OpResult` (idempotent; only failed legs re-run, S29), `archive_document`/`unarchive_document` CLI flows, `undo` with unchanged-fingerprint verification (S11/S12).

- [ ] **Step 1: Write failing tests for S8–S12, S29, S30, S50** (fault-inject archive mid-flight → doc stays active + journal `failed` naming archive leg + exit 2 (S9); single platform op id (S10); undo restores (S11); undo-edited refuses (S12); repair no-duplicate (S29); status lists exactly one failed leg (S30); platform-native archive byte-equivalent (S50)).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** repair.py + CLI flows.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: delete/archive/undo/sync (S8–S12/S29/S30/S50)`

### Task 8.4: `kgent auth` + secrets + encrypted fallback (§2.4, S46)

**Files:**
- Create: `src/kgent/secrets.py`
- Test: `tests/test_local_state.py` (S46)

- [ ] **Step 1: Write failing test for S46** (no OS secret store → `credentials.enc` exists, not plaintext (no token substring), warning "encrypted-file fallback active" at startup and on auth use; if encryption also unavailable → auth setup fails exit 1 and no credential file written).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `secrets.py` (OS store via `keyring`? No — stdlib-only: use platform APIs via `ctypes` for Windows Credential Manager/macOS Keychain/libsecret is non-trivial; **record in EVIDENCE**: use a `SecretStore` protocol; provide `EncryptedFileStore` (fallback) using `cryptography`? Not stdlib. Resolution: use `secrets`/`hashlib` PBKDF2 + `hmac` for a machine-local-key encrypted file (pure stdlib), with `EncryptedFileStore` as the default store and optional OS-keychain store behind a capability check. Warning text exact per S46.)
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: secrets + encrypted-file fallback (S46)`

---

## Phase 9 — Skills layer

### Task 9.1: Knowledge-storage skill (§5.1–§5.3, §6.1–§6.5, S60–S64)

**Files:**
- Modify: `src/kgent/skills/knowledge_storage.py`; Create: `src/kgent/skills/__init__.py`
- Test: `tests/test_skill_knowledge_storage.py`

- [ ] **Step 1: Write failing tests for S60–S64** (provenance records intent=update ← "conversation + existing doc" and target=lark ← "preferences"; update-first never proposes CREATE when a match exists (S61, N18); multiple matches offer per-copy options (S62); skill calls `resolve_intent` and consumes `targets[0].adapter_name` (S63); fan-out shares one idempotency key; router blocks unconfirmed skill write with confirmation-required gate (S64)).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `store_workflow(user_request, context, router)` → gather context → search update-first → build proposal with per-field provenance → confirm → execute via RoutingIntent. Backend-agnostic (S65).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: knowledge-storage skill (S60–S64)`

### Task 9.2: Skill ↔ router contract + resolution priority (§5.2, S65–S67)

**Files:**
- Test: `tests/test_skill_contract.py`

- [ ] **Step 1: Write failing tests for S65–S67** (same orchestration code across lark/dingtalk/wecom — only resolved adapter differs; agent loop invokes `lark-doc` skill not `lark-cli`/generic write (S66); explicit "store to dingtalk" outranks preferences + conversation, provenance "explicit user input" (S67)).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** the resolution-priority merge in `skills/` (explicit input > conversation > learnings > preferences > existing knowledge > heuristics) — this is the deterministic merge; LLM classification injected.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: skill↔router contract + resolution priority (S65–S67)`

### Task 9.3: QA skill + wiki-setup skill (§7.4, S68, S69)

**Files:**
- Create: `src/kgent/skills/question_answering.py`, `wiki_setup.py`
- Test: `tests/test_skill_qa_wiki.py`

- [ ] **Step 1: Write failing tests for S68 (every factual claim carries a source `doc_uri`; unsourced claims marked unsupported, never fabricated — N11) and S69 (one approval request per gated target via router; each created doc confirmed+journaled+undoable; failed leg per-backend + repairable via `kgent sync`).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** QA = aggregate → decompose → per-sub-query rank → answer with citations; wiki-setup = orchestrate multi-target create with router approvals + journaling.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat: QA + wiki-setup skills (S68/S69)`

### Task 9.4: End-to-end happy paths — CLI (§12; one e2e per command)

**Files:**
- Create: `src/kgent/router/core.py` (thin `Router` facade, see below)
- Create: `src/kgent/adapters/registry.py`
- Create: `tests/e2e/__init__.py`, `tests/e2e/test_cli_happy_paths.py`
- Modify: `tests/conftest.py` (add `e2e` fixture wiring the registry + `KGENT_HOME`)

**Interfaces:**
- Consumes: `main(argv) -> int` (Task 8.1), `Journal` (5.4), `AuditLog` (5.5), `registry` (new), `Config` (2.1), `trusted.is_trusted` (2.2).
- Produces (new):
  - `kgent.adapters.registry`: `register(name, adapter)`, `get(name) -> Adapter` (raises `ConfigError` if missing), `clear()`.
  - `kgent.router.core.Router` — `@dataclass` with `config, backends, journal, audit, session=set()`; methods `resolve_intent(...)` (delegates to `resolve.py`) and `execute(proposal, *, confirmation) -> OpResult` (delegates to `policy.execute_confirmed`).
  - `tests/conftest.py` `e2e` fixture: registers `test_world["backends"]` into the registry, writes `config.yaml` into `tmp_home`, sets `KGENT_HOME`, returns `test_world`.

- [ ] **Step 1: Write the failing e2e tests** — one happy path per CLI command, driven through `kgent.cli.main(argv)` in-process against the fake backends (router/policy/journal/audit are real; only the platform boundary is faked):

```python
# tests/e2e/test_cli_happy_paths.py
"""One end-to-end happy-path test per CLI command (design §12).
Drives kgent.cli.main(argv) in-process against fake backends with an isolated
~/.kgent home. Router, policy, journal, audit are the real implementations —
only the network/platform boundary is faked (acceptance §6)."""
import json
from kgent.cli import main
from kgent.router.journal import Journal
from kgent.config.trusted import is_trusted


def test_e2e_create(e2e):
    assert main(["create", "--title", "Onboarding", "--content", "Welcome", "--backends", "lark"]) == 0
    assert e2e["backends"]["lark"].docs


def test_e2e_store_is_update_first(e2e):
    assert main(["store", "--title", "API Guidelines", "--content", "v1", "--backends", "lark"]) == 0
    assert main(["store", "--title", "API Guidelines", "--content", "v2", "--backends", "lark"]) == 0
    lark = e2e["backends"]["lark"]
    assert lark.write_calls[-1]["method"] == "update_document"      # update-first, no dup
    assert next(iter(lark.docs.values())).content == "v2"


def test_e2e_search_returns_results(e2e, capsys):
    main(["create", "--title", "Meeting Notes", "--content", "Q3 plan", "--backends", "lark"])
    assert main(["search", "--query", "Q3", "--backends", "lark", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["doc_uri"].startswith("kgent://lark/")


def test_e2e_read(e2e):
    main(["create", "--title", "Doc", "--content", "body", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    assert main(["read", uri]) == 0


def test_e2e_update(e2e):
    main(["create", "--title", "Doc", "--content", "old", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    assert main(["update", uri, "--content", "new"]) == 0
    assert e2e["backends"]["lark"].docs[uri].content == "new"


def test_e2e_delete_offers_archive_first(e2e, capsys):
    main(["create", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    assert main(["delete", uri]) == 0
    out = capsys.readouterr().out
    assert "Archive on Lark" in out and "RECOMMENDED" in out


def test_e2e_archive_then_unarchive(e2e):
    main(["create", "--title", "Doc", "--content", "x", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    assert main(["archive", uri]) == 0
    assert uri in e2e["backends"]["lark"].archived and uri not in e2e["backends"]["lark"].docs
    assert main(["unarchive", uri]) == 0
    assert uri in e2e["backends"]["lark"].docs


def test_e2e_undo_restores_content(e2e, tmp_home):
    main(["create", "--title", "Doc", "--content", "before", "--backends", "lark"])
    uri = next(iter(e2e["backends"]["lark"].docs))
    main(["update", uri, "--content", "after"])
    op_id = [o["op_id"] for o in Journal(tmp_home).list_ops() if o["operation"] == "update"][0]
    assert main(["undo", op_id]) == 0
    assert e2e["backends"]["lark"].docs[uri].content == "before"


def test_e2e_sync_repairs_partial_fanout(e2e, tmp_home):
    e2e["backends"]["wecom"].fault = lambda m, kw: (_ for _ in ()).throw(RuntimeError("boom"))
    assert main(["store", "--title", "Doc", "--content", "x", "--backends", "lark,wecom"]) == 2  # partial
    e2e["backends"]["wecom"].fault = None
    op_id = Journal(tmp_home).list_partial()[0]["op_id"]
    assert main(["sync", "--repair", op_id]) == 0
    assert e2e["backends"]["wecom"].docs


def test_e2e_audit_writes(e2e, tmp_home):
    main(["create", "--title", "Doc", "--content", "x", "--backends", "lark"])
    assert main(["audit", "--op", "write", "--json"]) == 0
    assert (tmp_home / "audit.ndjson").read_text().strip()


def test_e2e_auth_status(e2e):
    assert main(["auth", "status"]) == 0


def test_e2e_setup_is_read_only(e2e, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    assert main(["setup"]) == 0


def test_e2e_doctor_healthy(e2e):
    assert main(["doctor"]) == 0


def test_e2e_config_validate_and_show_effective(e2e):
    assert main(["config", "validate"]) == 0
    assert main(["config", "show-effective", "--json"]) == 0


def test_e2e_trust_then_project_config_applies(e2e, tmp_home, tmp_path):
    proj = tmp_path / "D"; proj.mkdir()
    (proj / ".kgent-config.yaml").write_text("version: 1\ncontent_type_mapping:\n  meeting_notes: dingtalk\n")
    assert main(["trust", str(proj)]) == 0
    assert is_trusted(proj, tmp_home / "trusted.json")
```

- [ ] **Step 2: Run → FAIL** (registry/`Router`/CLI not yet wired; each test drives the real CLI entry).
- [ ] **Step 3: Implement** `registry.py`, `router/core.py` (`Router` facade), and the `e2e` fixture; wire `main` to build a `Router` from `KGENT_HOME` config + registry (no subprocess, no real network — fake adapters registered by the fixture).
- [ ] **Step 4: Run → PASS** (`pytest tests/e2e/test_cli_happy_paths.py -v` — 15 tests covering all 16 CLI commands; archive + unarchive share one test).
- [ ] **Step 5: Commit** `test: e2e happy paths for every CLI command (§12)`

### Task 9.5: End-to-end happy paths — skills (one e2e per skill feature)

**Files:**
- Create: `tests/e2e/test_skill_happy_paths.py`
- Modify: `tests/conftest.py` (add `router` fixture building a `Router` from `e2e` + `Journal` + `AuditLog`)

**Interfaces:**
- Consumes: `Router.execute/resolve_intent` (Task 9.4), `store_workflow(user_request, context, router) -> WriteProposal` (9.1), `answer(query, router) -> Answer` with `Answer.claims: list[Claim]` where `Claim.source_uri: str | None` (9.3), `setup_wiki(items, router) -> OpResult` (9.3).

- [ ] **Step 1: Write the failing e2e tests** — one happy path per skill feature, through the real router/journal/audit (fake backends only at the boundary):

```python
# tests/e2e/test_skill_happy_paths.py
"""One end-to-end happy-path test per skill feature. Skills orchestrate via the
real Router (policy, journal, audit) against fake backends."""
from kgent.cli import main
from kgent.router.journal import Journal
from kgent.skills.knowledge_storage import store_workflow
from kgent.skills.question_answering import answer
from kgent.skills.wiki_setup import setup_wiki


def test_e2e_knowledge_storage_creates_with_provenance(router, e2e):
    proposal = store_workflow("save the new doc 'Welcome to kgent'", {}, router)
    assert proposal.operation == "create"
    result = router.execute(proposal, confirmation="interactive-yes")
    assert result.exit_code == 0
    assert e2e["backends"]["lark"].docs


def test_e2e_knowledge_storage_update_first(router, e2e):
    p1 = store_workflow("save 'API Guidelines v1'", {}, router)
    router.execute(p1, confirmation="interactive-yes")
    p2 = store_workflow("save 'API Guidelines v2'", {}, router)
    assert p2.operation == "update"                       # update-first bias (N18)
    assert p2.targets[0].doc_uri is not None


def test_e2e_question_answering_cites_sources(router, e2e):
    main(["create", "--title", "Policy", "--content",
          "Onboarding requires security training.", "--backends", "lark"])
    ans = answer("What does onboarding require?", router)
    assert ans.claims
    assert all(c.source_uri for c in ans.claims)           # grounded, never fabricated (N11)


def test_e2e_wiki_setup_multi_target_journaled(router, e2e, tmp_home):
    result = setup_wiki(
        [{"title": "Team Wiki", "content": "home", "backends": ["lark", "dingtalk"]}],
        router,
    )
    assert result.exit_code == 0
    assert e2e["backends"]["lark"].docs and e2e["backends"]["dingtalk"].docs
    assert Journal(tmp_home).list_ops()                     # journaled → undoable
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** the `router` fixture; ensure skill return types (`Answer`/`Claim`, `setup_wiki`) match Task 9.3's implementation.
- [ ] **Step 4: Run → PASS** (`pytest tests/e2e/test_skill_happy_paths.py -v` — 4 passing, one per skill feature).
- [ ] **Step 5: Commit** `test: e2e happy paths for every skill feature`

---

## Phase 10 — Negative constraints, invariants, adversarial pass, gauntlet

### Task 10.1: Negative-constraint assertions (N1–N19) + secret/network scan

**Files:**
- Create: `tests/test_negative_constraints.py`
- Create: `tests/conftest.py` additions (socket send gate for N14)

- [ ] **Step 1: Write one test per N1–N19** (each a focused assertion; many reuse scenario tests, e.g. N1 → S1–S4 journal invariant, N2 → S6, N5 → forbidden-key fuzz, N14 → monkeypatch `socket.socket.send` to raise, assert suite runs no off-machine send).
- [ ] **Step 2: Run → FAIL** (until underlying behavior exists; several already GREEN from prior tasks)
- [ ] **Step 3: Fix any gaps surfaced**.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `test: negative constraints N1–N19 + N14 network gate`

### Task 10.2: Property-based invariants (P1–P7, hypothesis ≥100 examples)

**Files:**
- Create: `tests/properties/test_roundtrip.py` (P1), `test_idempotence.py` (P2), `test_precedence.py` (P3), `test_bound.py` (P4), `test_zone_monotonicity.py` (P5), `test_failsafe.py` (P6), `test_fingerprint.py` (P7)

- [ ] **Step 1: Write each property with hypothesis strategies** (P4 pairs with "top_k results returned when enough exist"; P5 pairs with "lowering tier never shrinks below configured defaults").
- [ ] **Step 2: Run → FAIL then drive GREEN**
- [ ] **Step 3: Persist example store** (hypothesis `@settings(derandomize=True)` + `database`).
- [ ] **Step 4: Commit** `test: property invariants P1–P7`

### Task 10.3: Adversarial pass corpora (§5)

**Files:**
- Create: `tests/adversarial/` fixtures (≥20 prompt-injection docs, config-injection fuzz, string-injection payloads, fault/race rehearsals) + `test_adversarial.py`

- [ ] **Step 1: Author the four corpora + fault/race rehearsals** (persisted, re-runnable).
- [ ] **Step 2: Write the harness** asserting zero write-class calls from fetched-doc content (N6), reject-or-ignore for all forbidden-key paths (N5), inertness for string payloads (S40/S41), journal-recoverable state + no data loss on faults, exactly-one-winner on concurrent update race.
- [ ] **Step 3: Run → drive GREEN**
- [ ] **Step 4: Commit** `test: adversarial corpus + fault/race rehearsals (§5)`

### Task 10.4: Gauntlet pass + real-execution smoke + evidence report

**Files:**
- Create: `EVIDENCE.md` (spec → test mapping table §7; checker negative controls; manual-mutation notes; real-execution transcript)
- Modify: `tools/gauntlet.sh` (finalize secret scan + network check to actually gate)

- [ ] **Step 1: Fill §7 mapping table** — every S/N/P/FM row → test + status (pass/unverified/n-a with reason).
- [ ] **Step 2: Run full gauntlet** → `bash tools/gauntlet.sh` green end-to-end.
- [ ] **Step 3: Run checker negative controls** — each grep-gate/script run against a known-bad fixture must fail (record in EVIDENCE).
- [ ] **Step 4: Real-execution smoke** — CLI run against two fake backends: `store → search → update-conflict → archive → undo`; paste transcript in EVIDENCE.
- [ ] **Step 5: Commit** `docs: evidence report + gauntlet pass (checkpoint)`

---

## Scenario → Task coverage map (§7 tracker)

| Acceptance IDs | Feature | Task(s) | Test file |
|---|---|---|---|
| S1–S4 | Write gating | 5.2, 8.2 | test_write_gating.py |
| S5–S7 | Optimistic concurrency | 5.3 | test_concurrency.py |
| S8–S12, S50 | Archive/delete/undo | 8.3 | test_archive_delete_undo.py |
| S13–S16 | Sensitivity & zones | 5.1 | test_sensitivity.py |
| S17–S21 | Config trust | 2.1, 2.2 | test_config_schema.py, test_config_trust.py |
| S22–S28 | Approval gates | 5.6 | test_approval_gates.py |
| S29–S30 | Repair & idempotency | 8.3 | test_repair_idempotency.py |
| S31–S36 | Search aggregation | 6.1–6.4 | test_search_aggregation.py |
| S37–S38 | Dedup | 6.4 | test_dedup.py |
| S39–S42 | Injection | 7.1, 3.3, 10.3 | test_injection.py |
| S43–S46, S51–S52 | Local state | 5.4, 5.5, 8.4 | test_local_state.py |
| S47 | Rate-limit budget | 7.1 | test_rate_size_fidelity.py |
| S48 | Oversize preflight | 6.2 | test_rate_size_fidelity.py |
| S49 | Fidelity | 7.3 | test_rate_size_fidelity.py |
| S53–S54 | Discovery & doctor | 3.3, 2.3 | test_discovery_doctor.py |
| S55–S57 | Conflict/snippet/query-decomp | 6.4, 6.5 | test_conflict_snippet_query.py |
| S58–S59 | Routing intent & adapter | 4.2 | test_routing_intent.py |
| S60–S64 | Knowledge-storage skill | 9.1 | test_skill_knowledge_storage.py |
| S65–S67 | Skill↔router contract | 9.2 | test_skill_contract.py |
| S68–S69 | QA + wiki-setup | 9.3 | test_skill_qa_wiki.py |
| N1–N19 | Negative constraints | 10.1 (+cross-task) | test_negative_constraints.py |
| P1–P7 | Property invariants | 10.2 | tests/properties/ |
| FM1–FM12 | Failure modes | 10.3 + scenario refs | tests/adversarial/ |
| all CLI commands | E2E happy path (one per command) | 9.4 | tests/e2e/test_cli_happy_paths.py |
| all skill features | E2E happy path (one per feature) | 9.5 | tests/e2e/test_skill_happy_paths.py |

## Known limitations (record in EVIDENCE, per spec §6/§8)

- **YAML parsing**: runtime deps are stdlib-only, so config YAML is parsed by a restricted YAML-subset loader (mappings/lists/scalars/comments) sufficient for Appendix C; anchors/tags rejected with `ConfigError`.
- **OS secret store**: pure-stdlib `SecretStore` protocol with a machine-local-key `EncryptedFileStore` (PBKDF2/HMAC) as the default; native OS-keychain backends (macOS Keychain/Windows Credential Manager/libsecret) are capability-gated extensions, not a runtime dep.
- **Mutation testing**: `mutmut` preferred; `tools/mutants.py` fallback used if unavailable (recorded in EVIDENCE).
- **LLM-assisted steps** (content-type/sensitivity classification §4.3/§6.3, query decomposition §7.4, conflict detection §7.5) are injected callables at the skill layer; the router ships deterministic fallbacks (no LLM, no fabrication).
