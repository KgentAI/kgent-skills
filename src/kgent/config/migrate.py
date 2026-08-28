"""Config version migration (§2.6).

``migrate_config`` upgrades an older config in place, writing a timestamped
backup ``config.yaml.bak-<ts>`` before any change. ``version: 1`` is the only
version that exists in this project, so it is a no-op; unknown versions are
backed up and left untouched so a subsequent load reports the ``kgent config
migrate`` hint (enforced by :func:`kgent.config.schema.load_config_dict`).
"""

from __future__ import annotations

import time
from pathlib import Path

from kgent.config import _yaml
from kgent.errors import ConfigError

__all__ = ["migrate_config"]


def migrate_config(path: Path) -> None:
    """Migrate ``path`` to the current config version, backing up first.

    ``version: 1`` (current) is a no-op. Older/unknown versions are backed up
    before any upgrade; since only version 1 exists today there is no concrete
    transformation, so the file is left in place and the schema surfaces the
    ``kgent config migrate`` hint on next load.
    """
    path = Path(path)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    raw = _yaml.parse(text)
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    if raw.get("version") == 1:
        return
    backup = path.with_name(f"{path.name}.bak-{int(time.time())}")
    backup.write_text(text, encoding="utf-8")
    # No older-version transformation exists in this project; leave the file
    # as-is so load_config_dict raises ConfigError with the migrate hint.
