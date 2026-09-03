# 0002 — `kgent doctor` does not flag `config.yaml.bak-*` files

The setup-merge spec suggested doctor could report `config.yaml.bak-*` files
as historical-overwrite hints (仅提示，不强求). We decided **not** to add that
finding: `doctor`'s contract maps *any* finding to exit 1
(`kgent/config/validate.py`), and since ADR-0001 every setup rerun leaves a
backup — the finding would make doctor permanently "unhealthy" for anyone who
has rerun setup even once.

Revisit only if `doctor` grows a non-failing "info" severity. Until then,
re-adding this check is a regression, not a fix.
