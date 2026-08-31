# Eval 2: "What's our policy on password rotation?" — With Skill

## Workflow Analysis

### Step 1: Analyze the Question

This is a **simple question** — one clear concept ("password rotation policy"). No decomposition into sub-queries is needed. The skill's Example 1 covers this exact pattern.

### Step 2: Search the Knowledge Base

**Command I would run:**

```bash
python -m kgent search --query "password rotation policy" --top-k 10 --json
```

**Actual result (from running the command):**

```json
{
  "results": [],
  "failures": [
    {
      "backend": "lark",
      "error": "AdapterError: adapter CLI failed with exit code 3: { ... lark-cli is not bound ... }",
      "timed_out": false
    }
  ],
  "footer": "1 backend failed",
  "schema_version": 1
}
```

The Lark backend failed because `lark-cli` is not configured/bound. No results were returned.

Per the skill, when the footer reports failures, I must mention it to the user:
> "Note: Lark search failed. The lark-cli adapter is not configured — run `lark-cli config bind` to set it up."

### Step 3: Read Relevant Documents

**Commands I would run (if results existed):**

```bash
python -m kgent read kgent://lark/<token1> --json
python -m kgent read kgent://lark/<token2> --json
python -m kgent read kgent://lark/<token3> --json
```

No documents to read since search returned empty results.

### Step 4: Read Config for Native URL Mapping

**Command I would run:**

```bash
cat ~/.kgent/config.yaml
```

**Actual result:**

```yaml
version: 1
defaults:
  workspace_domain: "your-workspace.larksuite.com"
backends:
  lark:
    enabled: true
    type: skill
    skill_name: lark-doc
    trust_zone: internal
```

`workspace_domain` is configured as `your-workspace.larksuite.com`, so URI→URL mapping would be:
- `kgent://lark/<token>` → `https://your-workspace.larksuite.com/docx/<token>`

### Step 5: Synthesize Answer

Since no results were found, I follow the skill's "No results found" pattern (Example 4).

---

## Answer Presented to User

I couldn't find any documents matching "password rotation policy" in the knowledge base.

**Note:** The Lark backend search failed because `lark-cli` is not configured. If a password rotation policy document exists in Lark, it may not be searchable until the adapter is set up. Run `lark-cli config bind` to configure it, then retry.

**Suggestions:**
- Try rephrasing with different keywords (e.g., "credential rotation", "password expiry", "security policy")
- Check with the Security or IT team directly
- Ask an admin if the document might be in a backend not yet configured in kgent

---

## Hypothetical Answer (If Results Were Found)

If the search had returned results, the answer would look like this (following the skill's Example 1 format):

> According to [Security Policy v2](https://your-workspace.larksuite.com/docx/abc123), passwords must be rotated every 90 days. [IT Guidelines](https://your-workspace.larksuite.com/docx/def456) adds that service accounts follow a different schedule (180 days).
>
> ---
> **Sources:**
> - [Security Policy v2](https://your-workspace.larksuite.com/docx/abc123) — Defines the 90-day password rotation rule for user accounts
> - [IT Guidelines](https://your-workspace.larksuite.com/docx/def456) — Documents the 180-day rotation schedule for service accounts

---

## Notes on Edge Cases & Compound Queries

### Compound Query Handling
If the user had asked "What's our password rotation policy and who enforces it?", I would decompose:
1. Sub-query 1: "password rotation policy"
2. Sub-query 2: "password rotation enforcement" / "security compliance owner"

I would show the decomposition to the user, run separate searches, and group results by sub-query in the final answer.

### Conflict Handling (S55)
If two documents disagreed (e.g., one says 90 days, another says 180 days), I would surface both with dates and let the user decide which is current — not silently pick one.

### Snippet Overlap (S56)
If multiple documents shared identical text, I'd note: "Documents A and B share identical policy language — likely derived from the same source. Treating as one authoritative source."

### Stale Results (S35)
If a `read` call failed because a document was deleted externally, I'd flag: "⚠️ One result (kgent://lark/xyz) appears to have been deleted since the search index was last updated."

### Sensitivity Awareness
A query about "password policy" could touch confidential security content. If the router limited results due to zone policies, I'd explain: "Note: Some backends returned limited results because the query may involve confidential content."

### Backend Failure Reporting (S33)
Always check the search result footer. If a backend timed out or failed, mention it transparently (as done above with the lark-cli config error).
