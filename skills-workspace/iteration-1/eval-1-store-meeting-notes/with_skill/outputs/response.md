# Eval 1: Store Meeting Notes (with_skill)

## User Prompt

> "We just finished our Q4 planning meeting. Here are the key decisions: 1) Focus on enterprise segment, 2) Hire 3 more engineers, 3) Launch beta by Nov 15. Can you save these meeting notes?"

## Skill Activation

Trigger: user intent to **write** ("Can you save these meeting notes?"). This matches the `knowledge-storage` skill — the write path. If the goal were to read/retrieve, `question-answering` would apply instead.

---

## Step 1 — Extract Knowledge

From the conversation, derive:

- **Title**: `Q4 Planning Meeting Notes` (derived from context — user said "Q4 planning meeting" and "save these meeting notes")
- **Content** (reformatted as clean markdown, not raw chat text):

```markdown
# Q4 Planning Meeting Notes

## Key Decisions

1. **Focus on enterprise segment** — strategic priority for Q4.
2. **Hire 3 more engineers** — expand the engineering team.
3. **Launch beta by Nov 15** — hard deadline for the beta release.

## Context

- Meeting date: 2026-08-31
- Decisions captured directly from participants.
```

- **Target backend**: `lark` ← config default (user did not specify a backend; per the skill's resolution priority S67, we fall back to `defaults.default_backends` from `~/.kgent/config.yaml`, which is typically `lark`).

---

## Step 2 — Update-First Search

Before creating, search for existing similar content (update-first bias N18, S61):

```bash
python -m kgent search --query "Q4 Planning Meeting" --backends lark --top-k 5 --json
```

**Expected result for this eval**: no matches found (we assume a fresh knowledge base for this scenario).

→ Propose **creating** a new document.

Record provenance:
- intent: create (no matching docs found via search)
- target: lark ← config default
- title source: derived from user's "Q4 planning meeting" phrasing

---

## Step 3 — Proposal Presented to User

```
I'll create a new document:

  Title:   Q4 Planning Meeting Notes
  Backend: lark
  Content:
    # Q4 Planning Meeting Notes

    ## Key Decisions
    1. Focus on enterprise segment — strategic priority for Q4.
    2. Hire 3 more engineers — expand the engineering team.
    3. Launch beta by Nov 15 — hard deadline for the beta release.

    ## Context
    - Meeting date: 2026-08-31
    - Decisions captured directly from participants.

  Provenance:
  - intent:   create ← no matching docs found via search
  - target:   lark ← config default (defaults.default_backends)
  - title:    derived from "Q4 planning meeting" in your message

Create it? (yes/no/edit)
```

I then **wait for explicit user approval** (N1, S64 — never execute without it). If the user says `edit`, I revise title/content and re-present. If `no`, I abort.

---

## Step 4 — Execute (After User Says "yes")

```bash
python -m kgent store \
  --title "Q4 Planning Meeting Notes" \
  --content "# Q4 Planning Meeting Notes\n\n## Key Decisions\n1. **Focus on enterprise segment** — strategic priority for Q4.\n2. **Hire 3 more engineers** — expand the engineering team.\n3. **Launch beta by Nov 15** — hard deadline for the beta release.\n\n## Context\n- Meeting date: 2026-08-31\n- Decisions captured directly from participants." \
  --backends lark \
  --yes \
  --json
```

Parse the JSON output for `op_id` and the target URI (e.g. `kgent://lark/tok_abc123`).

---

## Step 5 — Convert to Native URL and Confirm

1. Read `~/.kgent/config.yaml` → `defaults.workspace_domain` (e.g. `mycompany.larksuite.com`).
2. Apply Lark mapping (N20, S73):
   - `kgent://lark/tok_abc123` → `https://mycompany.larksuite.com/docx/tok_abc123`

**Confirmation message** (what the user actually sees):

```
✅ Created: "Q4 Planning Meeting Notes" → https://mycompany.larksuite.com/docx/tok_abc123
   Op ID: op-7f3a9c (undo via: kgent undo op-7f3a9c)
```

If `workspace_domain` were **not** configured (S75), the fallback message would be:

```
✅ Created: "Q4 Planning Meeting Notes" → kgent://lark/tok_abc123
   Op ID: op-7f3a9c (undo via: kgent undo op-7f3a9c)

To see native platform URLs, add `workspace_domain` to your config at
`~/.kgent/config.yaml` under `defaults:`. For example:
  workspace_domain: mycompany.larksuite.com
```

---

## Provenance Summary (included in proposal and logged with the operation)

| Field    | Value                              | Source                                |
|----------|------------------------------------|---------------------------------------|
| intent   | create                             | no matching docs found via search     |
| title    | Q4 Planning Meeting Notes          | derived from user's "Q4 planning meeting" phrasing |
| backend  | lark                               | config default (`defaults.default_backends`) |
| content  | structured markdown                | reformatted from raw user input       |
| op_id    | op-7f3a9c                          | returned by `kgent store`             |
| uri      | kgent://lark/tok_abc123            | returned by `kgent store`             |
| native   | https://mycompany.larksuite.com/docx/tok_abc123 | derived via `workspace_domain` |

---

## Commands Run, in Order

1. `python -m kgent search --query "Q4 Planning Meeting" --backends lark --top-k 5 --json`
2. *(after user approval)* `python -m kgent store --title "Q4 Planning Meeting Notes" --content "..." --backends lark --yes --json`
3. Read `~/.kgent/config.yaml` to resolve `defaults.workspace_domain` for native URL conversion.

---

## Notes on This Eval

- The `lark-cli` binary is not installed in this environment, so the actual `kgent` commands would fail at runtime. This eval demonstrates the **intended workflow** — extraction, update-first search, proposal, execution, native URL conversion — as the skill specifies.
- No sensitivity-zone content (N4, S13–S15) is present — the meeting notes are not classified, so no internal-zone-only routing is needed.
- The content did not originate from a fetched document, so the embedded-instruction trap (N6, S39) does not apply.
- No version conflict expected on create; conflict handling (S6) would only trigger on an update path.
