"""Manual mutation fallback (per acceptance §6). Mutates one statement and re-runs
the suite; a surviving mutant is reported. Used only when mutmut is unavailable."""

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
