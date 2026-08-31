---
name: question-answering
description: "Answer questions using the knowledge base via kgent CLI. Activate when the user asks about information that might be stored in the knowledge base (e.g., 'what does X mean?', 'how do we handle Y?', 'do we have docs about Z?'). Provides grounded answers with source citations."
metadata:
  requires:
    bins: ["python"]
---

# Question Answering

Answer questions using the knowledge base. This skill searches across configured backends and presents information with source citations.

## When to Use

Activate this skill when the user:
- Asks "what", "how", "why" questions about internal processes, documentation, or knowledge
- Says "do we have documentation about...", "what's our policy on..."
- Asks about information that might be stored in the knowledge base
- Wants to retrieve specific knowledge from Lark, DingTalk, or other backends

## Workflow

### 1. Extract Search Query

From the user's question, identify key search terms:
- Remove stop words (the, a, is, etc.)
- Focus on domain-specific terms and concepts
- Consider synonyms and related terms

### 2. Search the Knowledge Base

Search across all configured backends (or specific ones if the user mentions them):

```bash
python -m kgent search --query "<search terms>" --top-k 10 --json
```

Or search specific backends:
```bash
python -m kgent search --query "<search terms>" --backends lark --top-k 10 --json
```

### 3. Read Relevant Documents

For the most relevant results, read the full documents:

```bash
python -m kgent read <doc_uri> --json
```

Read 2-5 of the most relevant documents to gather comprehensive information.

### 4. Synthesize Answer

Combine information from the documents into a coherent answer:
- **Cite sources**: Every factual claim should reference the source document URI
- **Handle conflicts**: If documents contradict each other, note the discrepancy
- **Mark uncertainty**: If information is incomplete or unclear, say so
- **Structure clearly**: Use headings, lists, and formatting for readability

### 5. Present Answer with Citations

Format the answer with inline citations:

```
Based on the knowledge base:

## <Answer Summary>

<Answer content with citations>

According to [Document Title](doc_uri), ...
Additionally, [Another Document](doc_uri) mentions...

---
Sources:
- [Document Title 1](kgent://lark/abc123)
- [Document Title 2](kgent://lark/def456)
```

## Important

- **Always cite sources**: Never present information without referencing where it came from.
- **Use native URLs**: Read `workspace_domain` from `~/.kgent/config.yaml` and convert `kgent://` URIs to native platform URLs in citations (e.g., `https://mycompany.larksuite.com/docx/<token>` for Lark).
- **Be transparent about gaps**: If the knowledge base doesn't have the answer, say so clearly.
- **Don't fabricate**: Only use information from the search results; don't add external knowledge.
- **Respect scope**: If the question is about something not in the knowledge base, suggest alternative sources.
- **Handle no results**: If search returns empty, inform the user and suggest rephrasing or checking with an admin.

## Examples

**Example 1: Simple factual question**
```
User: "What's our policy on password rotation?"

Skill:
1. Search: python -m kgent search --query "password rotation policy" --json
2. Read top 2-3 results
3. Read workspace_domain from config: "mycompany.larksuite.com"
4. Synthesize: "According to [Security Policy v2](https://mycompany.larksuite.com/docx/abc123), passwords must be rotated every 90 days. The [IT Guidelines](https://mycompany.larksuite.com/docx/def456) adds that service accounts follow a different schedule (180 days)."

---
Sources:
- [Security Policy v2](https://mycompany.larksuite.com/docx/abc123)
- [IT Guidelines](https://mycompany.larksuite.com/docx/def456)
```

**Example 2: Process question**
```
User: "How do we deploy to production?"

Skill:
1. Search: python -m kgent search --query "production deployment process" --json
2. Read relevant documents
3. Read workspace_domain from config: "mycompany.larksuite.com"
4. Synthesize: "Based on [Deployment Guide](https://mycompany.larksuite.com/docx/xyz789), the production deployment process is: 1) ... 2) ... 3) ... Note: [Recent Update](https://mycompany.larksuite.com/docx/uvw321) mentions we've switched to blue-green deployments."

---
Sources:
- [Deployment Guide](https://mycompany.larksuite.com/docx/xyz789)
- [Recent Update](https://mycompany.larksuite.com/docx/uvw321)
```

**Example 3: No results found**
```
User: "What's the vacation policy?"

Skill:
1. Search: python -m kgent search --query "vacation policy" --json
2. No results
3. Respond: "I couldn't find documentation about the vacation policy in the knowledge base. You might want to check with HR or look in the employee handbook."
```
