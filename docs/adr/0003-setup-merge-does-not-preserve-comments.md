# 0003 — setup's config merge re-dumps the file; comments are not preserved

`write_setup_config` merges by parse → re-dump (the YAML-subset emitter in
`kgent.capabilities.setup_config`), so all *values* survive a rerun but
comments and original formatting do not; the `.bak-<ts>` copy retains the
original bytes. The alternative — text-splicing merged values into the
existing file to preserve bytes, like `kgent config set-workspace-domain`'s
surgical `_inject_key` — was rejected: setup replaces the whole `backends`
section (reordering, key fill-in, appended entries), which cannot be spliced
reliably with a line-based editor.

This asymmetry with `set-workspace-domain` (which does preserve comments) is
deliberate: one key can be injected in place; a structural merge cannot.
