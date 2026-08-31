"""Grade skill eval outputs against assertions in eval_metadata.json.

Checks each assertion's verification condition against the response.md file
and produces grading.json per the skill-creator schema.
"""
import json
import re
import sys
from pathlib import Path


def check_assertion(assertion: dict, response: str) -> tuple[bool, str]:
    """Return (passed, evidence) for one assertion."""
    name = assertion["name"]
    verification = assertion["verification"]
    response_lower = response.lower()

    # Parse verification DSL (simple pattern matching)
    if name == "update_first_search":
        has_search = "python -m kgent search" in response
        search_pos = response.find("python -m kgent search")
        create_pos = response.find("python -m kgent create")
        store_pos = response.find("python -m kgent store")
        first_write = min(p for p in [create_pos, store_pos] if p >= 0) if any(p >= 0 for p in [create_pos, store_pos]) else len(response)
        passed = has_search and (search_pos < first_write)
        evidence = f"search at pos {search_pos}, first write at pos {first_write}" if has_search else "no search command found"
        return passed, evidence

    elif name == "proposal_displayed":
        has_proposal = any(kw in response_lower for kw in ["proposal", "i'll create", "i found", "create it?", "proceed?"])
        evidence = "proposal/confirmation prompt found" if has_proposal else "no proposal/confirmation prompt found"
        return has_proposal, evidence

    elif name == "title_derived":
        has_title = any(kw in response for kw in ["Title:", "title=", "Q4", "Planning", "Meeting"])
        evidence = "title field found in response" if has_title else "no title field found"
        return has_title, evidence

    elif name == "content_formatted_markdown":
        has_md = any(kw in response for kw in ["##", "- ", "* ", "```", "###"])
        evidence = "markdown formatting found" if has_md else "no markdown formatting found"
        return has_md, evidence

    elif name == "native_url_in_confirmation":
        has_https = "https://" in response
        # Find the primary confirmation section (first occurrence of confirmation pattern)
        conf_markers = ["✅ created", "✅ updated", "created:", "updated:"]
        conf_start = -1
        for marker in conf_markers:
            pos = response.lower().find(marker)
            if pos >= 0 and (conf_start < 0 or pos < conf_start):
                conf_start = pos
        # Also accept "confirmation message" section headers
        if conf_start < 0:
            for marker in ["confirmation message", "confirmation:", "**confirmation"]:
                pos = response.lower().find(marker)
                if pos >= 0 and (conf_start < 0 or pos < conf_start):
                    conf_start = pos
        if conf_start >= 0:
            # Check first 500 chars of confirmation for native URL
            conf_section = response[conf_start:conf_start + 500]
            primary_has_native = "https://" in conf_section
            # If primary confirmation has native URL, that's enough even if fallback mentions kgent://
            passed = primary_has_native
            evidence = f"primary confirmation has https://: {primary_has_native}"
        else:
            passed = has_https
            evidence = f"response has https://: {has_https} (no distinct confirmation section found)"
        return passed, evidence

    elif name == "op_id_reported":
        has_opid = any(kw in response_lower for kw in ["op_id", "op id", "op-", "undo"])
        evidence = "op_id/undo reference found" if has_opid else "no op_id/undo reference found"
        return has_opid, evidence

    elif name == "provenance_shown":
        has_prov = any(kw in response_lower for kw in ["provenance", "target:", "config default", "explicit", "preferences"])
        evidence = "provenance info found" if has_prov else "no provenance info found"
        return has_prov, evidence

    elif name == "search_executed":
        has_search = "python -m kgent search" in response
        has_relevant = any(kw in response_lower for kw in ["password", "rotation", "policy"])
        passed = has_search and has_relevant
        evidence = f"search found: {has_search}, relevant terms: {has_relevant}"
        return passed, evidence

    elif name == "documents_read":
        has_read = "python -m kgent read" in response
        evidence = "read command found" if has_read else "no read command found"
        return has_read, evidence

    elif name == "claims_cited":
        # Check for inline citations like [Title](url) or [Title](...)
        has_citations = bool(re.search(r'\[[^\]]+\]\([^)]+\)', response))
        evidence = "inline citations found" if has_citations else "no inline citations found"
        return has_citations, evidence

    elif name == "native_url_citations":
        has_kgent_url = bool(re.search(r'kgent://[^\s\)]+', response))
        has_https_url = "https://" in response
        passed = has_https_url and not has_kgent_url
        evidence = f"https URLs: {has_https_url}, kgent:// URLs: {has_kgent_url}"
        return passed, evidence

    elif name == "sources_section":
        has_sources = any(kw in response for kw in ["Sources:", "## Sources", "**Sources**", "sources:"])
        evidence = "sources section found" if has_sources else "no sources section found"
        return has_sources, evidence

    elif name == "no_fabrication":
        # Check that policy details are attributed
        has_attribution = any(kw in response_lower for kw in ["according to", "source:", "document", "[", "states", "says"])
        evidence = "attribution language found" if has_attribution else "no attribution language found"
        return has_attribution, evidence

    return False, f"unknown assertion: {name}"


def grade_run(eval_dir: Path, run_dir: Path) -> dict:
    """Grade one run directory. eval_dir is the parent (holds eval_metadata.json), run_dir is with_skill/without_skill."""
    metadata_path = eval_dir / "eval_metadata.json"
    response_path = run_dir / "outputs" / "response.md"

    if not metadata_path.exists():
        return {"error": f"no metadata at {metadata_path}"}
    if not response_path.exists():
        return {"error": f"no response at {response_path}"}

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    response = response_path.read_text(encoding="utf-8")

    expectations = []
    passed_count = 0
    for assertion in metadata["assertions"]:
        passed, evidence = check_assertion(assertion, response)
        if passed:
            passed_count += 1
        expectations.append({
            "text": assertion["check"],
            "passed": passed,
            "evidence": evidence,
        })

    total = len(expectations)
    return {
        "expectations": expectations,
        "summary": {
            "passed": passed_count,
            "failed": total - passed_count,
            "total": total,
            "pass_rate": round(passed_count / total, 2) if total > 0 else 0,
        },
    }


def main():
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("skills-workspace/iteration-1")
    results = {}
    for eval_dir in sorted(workspace.iterdir()):
        if not eval_dir.is_dir() or eval_dir.name.startswith("."):
            continue
        for config_dir in eval_dir.iterdir():
            if not config_dir.is_dir():
                continue
            run_dir = config_dir
            grading = grade_run(eval_dir, run_dir)
            key = f"{eval_dir.name}/{config_dir.name}"
            results[key] = grading
            # Write grading.json
            (run_dir / "grading.json").write_text(json.dumps(grading, indent=2))
            status = "PASS" if grading.get("summary", {}).get("pass_rate", 0) >= 0.8 else "FAIL"
            pr = grading.get("summary", {}).get("pass_rate", "N/A")
            print(f"  {status} {key}: {pr} pass rate")

    # Summary
    print("\n" + "=" * 60)
    with_skill = {k: v for k, v in results.items() if "with_skill" in k}
    without_skill = {k: v for k, v in results.items() if "without_skill" in k}
    ws_avg = sum(v.get("summary", {}).get("pass_rate", 0) for v in with_skill.values()) / max(len(with_skill), 1)
    wos_avg = sum(v.get("summary", {}).get("pass_rate", 0) for v in without_skill.values()) / max(len(without_skill), 1)
    print(f"With skill avg:    {ws_avg:.0%}")
    print(f"Without skill avg: {wos_avg:.0%}")
    print(f"Delta:             {ws_avg - wos_avg:+.0%}")


if __name__ == "__main__":
    main()
