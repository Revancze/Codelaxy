### Index identity (I) — canonical v2

Domain: `codelaxy.snapshot.index.v2`. Source: `git ls-files --stage -t -z`.

| Rule | Value |
|---|---|
| Entry fields | mode, object id (full hex), stage (decimal), path — in this order |
| Entry order | path by UTF-16 code units (`StringComparer.Ordinal`), then stage, mode, object id |
| Framing | the domain, then every field, each as `uint32 big-endian byte length` + UTF-8 bytes; no other separators |
| Hash | SHA-256, rendered `sha256:` + lowercase hex |
| Not included | the skip-worktree flag (a local checkout policy, not staged content); index stat data |
| Empty index | the hash of the framed domain alone |

Golden evidence: `GitSnapshotIndexGoldenTests` (INDEX-GOLDEN-001,
INDEX-GOLDEN-UNICODE-001). Expected values are computed independently of the
implementation (Python `hashlib`; blob ids cross-checked with `git hash-object`).

#### Known property: UTF-16 order differs from Git's order

Git orders index paths by their raw bytes; canonical v2 orders paths by UTF-16 code
units. The two agree except when a path compares a supplementary character
(U+10000 and above, e.g. emoji) against a BMP character in U+E000–U+FFFF:
UTF-16 places `😀.txt` before `.txt`, raw-byte order places it after.

Both orders are deterministic: for identical canonical inputs, I is stable across Git
versions. Canonical v2 deliberately keeps the UTF-16 order; INDEX-GOLDEN-UNICODE-001
pins it. Switching to UTF-8 byte order would change I for affected repositories
and therefore requires a new domain version (`index.v3`).

Paths are hashed exactly as Git reports them: no Unicode normalization, so NFC
and NFD spellings of a name remain distinct entries.
