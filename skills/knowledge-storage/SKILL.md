---
name: knowledge-storage
description: "Persist knowledge from conversations into the knowledge base using kgent CLI. Activate when the user wants to save, store, or persist conversation knowledge. Supports multiple backends (Lark, DingTalk, WeCom). Update-first workflow: searches for existing documents before creating new ones."
metadata:
  requires:
    bins: ["python"]
---

# Knowledge Storage

Save knowledge from conversations to the knowledge base using the kgent CLI. This skill orchestrates the `kgent store` command with update-first semantics.

## When to Use

Activate this skill when the user:
- Wants to "save", "store", or "persist" information from the conversation
- Asks to "remember" something for later
- Says things like "save this to our knowledge base", "store these notes", "add this to the wiki"
- Wants to update existing documentation with new information

## Workflow

### 1. Extract Knowledge

From the conversation context, identify:
- **Title**: A concise, descriptive title
- **Content**: The knowledge to persist (in markdown format)
- **Target backend**: Which backend(s) to store to (default: from config, typically `lark`)

### 2. Check for Existing Content (Update-First)

Before creating a new document, search for existing similar content:

```bash
python -m kgent search --query "<title keywords>" --backends <backend> --json
```

Analyze the results:
- If a document with the same or very similar title exists → propose updating it
- If no similar content exists → propose creating a new document

### 3. Present Proposal

**For new documents:**
```
I'll create a new document:

Title: <title>
Backend: <backend>
Content:
<content preview>

Create it? (yes/no/edit)
```

**For updates:**
```
I found a similar existing document: "<existing title>"
URI: <doc_uri>

I propose updating it with the following content:
<content preview>

Proceed? (yes/no/edit)
```

### 4. Execute (After User Approval)

**Create new document:**
```bash
python -m kgent store --title "<title>" --content "<content>" --backends <backend> --json
```

**Update existing document:**
```bash
python -m kgent update --uri <doc_uri> --content "<content>" --json
```

### 5. Confirm

Report the result to the user:
- For new documents: show the native platform URL and confirm creation
- For updates: show the native platform URL and confirm the update

**Convert kgent URI to native URL:**

Read the workspace domain from `~/.kgent/config.yaml` (`defaults.workspace_domain`), then:
- Lark: `kgent://lark/<token>` → `https://<workspace_domain>/docx/<token>`
- DingTalk: `kgent://dingtalk/<id>` → (DingTalk URL format)
- WeCom: `kgent://wecom/<id>` → (WeCom URL format)

Example: If `workspace_domain: "mycompany.larksuite.com"` and URI is `kgent://lark/abc123`, the native URL is `https://mycompany.larksuite.com/docx/abc123`.

## Important

- **Never store without explicit user approval.** Always present the proposal first.
- **Update-first bias:** Always search for existing content before creating new documents.
- **Well-structured content:** Format the content as clean markdown, not raw conversation text.
- **Backend selection:** If the user doesn't specify a backend, use the configured default (check `~/.kgent/config.yaml`).
- **Support iterative refinement:** If the user wants to change the title or content, revise and present again.
- **Show native URLs:** Always convert `kgent://` URIs to native platform URLs when confirming with the user.

## Examples

**Example 1: Storing meeting notes**
```
User: "We just discussed the new authentication flow. Can you save these notes?"

Skill:
1. Extract: title="Authentication Flow Discussion", content="## Key Decisions\n- Using OAuth 2.0 with PKCE\n- Token refresh every 15 minutes..."
2. Search: python -m kgent search --query "Authentication Flow" --backends lark --json
3. No similar docs found → propose creating new
4. User approves → python -m kgent store --title "Authentication Flow Discussion" --content "..." --backends lark
5. Response: {"targets": ["kgent://lark/abc123"]}
6. Read workspace_domain from config: "mycompany.larksuite.com"
7. Convert to native URL: https://mycompany.larksuite.com/docx/abc123
8. Confirm: "✅ Created document: https://mycompany.larksuite.com/docx/abc123"
```

**Example 2: Updating existing documentation**
```
User: "The deployment guide needs to be updated - we're now using Docker."

Skill:
1. Search: python -m kgent search --query "deployment guide" --backends lark --json
2. Found: "Deployment Guide v1" (kgent://lark/xyz789)
3. Propose update with new Docker-based content
4. User approves → python -m kgent update --uri kgent://lark/xyz789 --content "..."
5. Read workspace_domain from config: "mycompany.larksuite.com"
6. Convert to native URL: https://mycompany.larksuite.com/docx/xyz789
7. Confirm: "✅ Updated document: https://mycompany.larksuite.com/docx/xyz789"
```
