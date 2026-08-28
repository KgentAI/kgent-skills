"""Fake backend CLI for S40: records the exact argv a subprocess received.

``run_cli`` must pass user-supplied strings as discrete argv elements — never
through a shell. This stub writes ``sys.argv`` verbatim to the JSON path named
by ``FAKE_CLI_ARGV_OUT`` so tests can assert the argument array byte-for-byte
(metacharacters like ``;``, ``#`` must arrive inert, un-split, un-interpreted).
"""

from __future__ import annotations

import json
import os
import sys

ARGV_OUT_ENV = "FAKE_CLI_ARGV_OUT"


def main() -> int:
    out = os.environ.get(ARGV_OUT_ENV)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"argv": list(sys.argv)}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
