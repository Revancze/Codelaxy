# Catalog specs for the real MICROMAP corpus

These files are the *documented* source of the machine-local catalogs. Nothing in them is a historical claim without a basis that the tools re-check.

| File | Content | Checked by |
|---|---|---|
| `sources.spec.json` | the four pinned documents (MICROMAP rev. 1, the ratified rev. 2 bytes, the marked file, the ratification record). Every version carries the basis of its hash (a literal quote that contains it, found in another catalogued file, or the protected-files manifest) and of its status (a literal quote) | `localcat build-sources` refuses the whole build if a hash, a file or a quote does not match |
| `namespaces.micromap.json` | the label namespaces defined by the "Naming" section of the ratified MICROMAP (plus R1-R3 of revision 1 and R0-R4 of docs/branching.md). Every authority carries a literal quote | `localcat check` (quotes required) |
| `ambiguity.micromap.json` | the one ambiguity the document states itself: a step written without the `P1.2-` prefix | `ledger build` validates it against the namespaces |
| `run.micromap.json` | which source versions are imported | `ledger build` |

Namespaces not documented in the corpus (for example D1-D12 of docs/branching.md) are deliberately absent; their labels appear in the ledger as `UNCLASSIFIED_LABEL`.

## Reproduce and check

```text
python -m clxreg.localcat build-sources --spec catalog-specs/sources.spec.json --manifest local/protected-manifest.json --root workspace=<CodelaxyWorkspace> --out local/sources.json
python -m clxreg.localcat check --spec catalog-specs/sources.spec.json --manifest local/protected-manifest.json --root workspace=<CodelaxyWorkspace> --catalog local/sources.json --namespaces catalog-specs/namespaces.micromap.json
python -m clxreg.ledger build --run catalog-specs/run.micromap.json --catalog local/sources.json --namespaces catalog-specs/namespaces.micromap.json --ambiguity catalog-specs/ambiguity.micromap.json --root workspace=<CodelaxyWorkspace> --out <new ledger file>
```

`local/protected-manifest.json` is built by `python -m clxreg.protect build` from the hashes documented in the phase-1 INVENTORY (it refuses when the disk differs from a documented hash).
Its five `testrun` entries were computed on 2026-11-01 and have no earlier documented hash.
