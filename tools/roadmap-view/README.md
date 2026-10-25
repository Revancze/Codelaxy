# roadmap-view

A **read-only, translatable HTML view** of `Codelaxy-Roadmap.ods`. The workbook itself is never
changed; the Czech (or any other) reading aid appears next to it.

```
python roadmap_view.py build      # docs/Codelaxy-Roadmap.ods  ->  docs/roadmap-view/Codelaxy-Roadmap.html + lang/cs.js
python roadmap_view.py check      # do the files in out/ equal what the current ODS produces?  (exit 1 if not)
python roadmap_view.py watch      # rebuild automatically whenever the ODS is saved (see below)
python roadmap_view.py status     # how much of lang/cs.src.json is translated / missing / stale
python roadmap_view.py merge lang/chunks/cNN.json   # add reviewed translations ({"<index>": "text"}), validated
```

Open `docs/roadmap-view/Codelaxy-Roadmap.html` by double-click. It needs no server and no network. Keep the
`lang/` folder next to it: a language pack is only loaded when the reader picks that language.

## What the reader sees

* The four sheets, with the workbook's colours, merged cells, links between sheets and the status colours
  (DONE, PARTIAL, PLANNED, BLOCKED, UNKNOWN). Stored formula results are shown; nothing is recalculated.
* A banner with the **reference commit and inventory date taken from the workbook** (`b05f2d2`, 2026-10-18)
  and the SHA-256 and git blob id of the ODS it was generated from. It says plainly that this is a historical
  snapshot, not the current project status.
* A language picker. **English** is the original. **Čeština** loads `lang/cs.js` (translated in advance). **Other language** asks the browser's on-device `Translator` for any other code (`ja`, `de`, ...).
* Hover, keyboard focus or tap on a cell shows its translation in a bubble. Enter/Space pins it, Esc closes it.
* The choice is remembered: URL fragment (`#lang=cs`) first, then the browser's saved choice, then English.
  A browser without usable storage still works; it just forgets.

Only the language the reader chooses is loaded (Czech is one 89 KB file; other languages cost nothing until chosen).
For languages without a pack the browser downloads one translation model, once, on the reader's click.

## Design rules (from the independent review) and where they are enforced

| Rule | How | Test |
|---|---|---|
| The ODS stays byte-identical | opened `"rb"` only; SHA-256 + git blob taken before and after every command; output folder may not contain the ODS | `OriginalIntegrity` |
| Works from disk, offline | data is in the HTML; the language pack is a `<script src>` (works on `file://`, unlike `fetch`) | `BrowserFromDisk` (real Chrome, `file://`) |
| Storage is optional | every `localStorage` access is in try/catch; fragment wins over storage | `BrowserFromDisk.test_storage_that_throws...` |
| Translation is bound to its source | stable key `SHEET!CELL` + 16-hex hash of the normalised English text (NFC, LF, no trailing blanks) | `TranslationBinding` |
| Changed English never shows an old translation | the cell's hash must equal the pack's hash, otherwise the bubble says "outdated" and shows no translation | `TranslationBinding`, `BrowserFromDisk` |
| Pack/page generated from different ODS versions | `check` regenerates in memory and compares with the files on disk | `test_generation_check_notices...` |
| Missing translation falls back to English | bubble says so; the English text is on the page | `BrowserFromDisk` |
| Translator API unavailable never blocks reading | feature detection, 6 s availability timeout, explicit download button, every failure ends in English + a readable message | `BrowserFromDisk` |
| Protected tokens are separated structurally | IDs, statuses, files, identifiers, hashes, `backticks`, `[D]/[I]`, quotes are found by code (`rv_text.tokenize`), wrapped in `<span class="np" translate="no">` and sent to a translator as placeholders `⟦n⟧`, then verified (otherwise translated part by part, otherwise refused) | `ProtectedTokens` |
| Hostile cell content cannot run | everything escaped; only `http(s)` and `#Sheet.Cell` become links; CSP `default-src 'none'; connect-src 'none'` | `HostileContent` (incl. real browser) |
| Deterministic | no timestamps, no machine paths, sorted keys | `Determinism` |
| Validations (dropdowns) are not editable | none of `input/select/textarea` inside the sheets; the 10 editing-hint notes are omitted | `EnglishFidelity` |
| Live update is safe | settles two polls, retries half-written files, never writes the watched file | `LiveUpdate` |
| The tests can fail | 15 deliberate breakages, each must turn an invariant RED (plus a green control run) | `test_mutations.py` |

## Keeping it up to date while the workbook is edited

```
python tools/roadmap-view/roadmap_view.py watch
```

Leave it running while you edit in LibreOffice. When you save, the view is rebuilt within a few seconds (press F5 in the browser).
The watched file is only read. A save is acted on once the file has stayed the same for two polls; a half-written file is retried.

What updates by itself: all English text, structure, colours, statuses, links, the banner's SHA-256 / git blob.
What does **not** update by itself: the Czech wording of text you changed. Those cells immediately show "outdated/missing" in the bubble
(never the old translation) and are listed in `work/todo.cs.json` as `{"<index>": "English text"}`. Translate them (ask Claude, or by hand)
into a chunk file and run `merge`; the next save or `build` picks them up. Statuses, IDs and dates need no translation.

Any Chromium browser (Chrome, Edge, Brave) can open the view; the Czech pack does not depend on the browser. Translation into *other*
languages uses the browser's on-device `Translator` API, which Brave may not provide or may restrict: not tested here.

## What this is not

* **Not a Czech edition of the workbook.** The workbook's own point **OPEN-15** says "No Czech version was produced.
  Ratify or request a Czech edition." This view is a reading aid; the English text is authoritative and every bubble says so.
  It does not answer OPEN-15.
* **Not the current project status.** The ODS is the 2026-10-18 reference state (`b05f2d2`). For example it still lists
  T1/T2 as PLANNED although PR #14 and PR #15 are merged. The ratified sources are `docs/roadmap.md` (revision 7) and
  `docs/architecture.md`; project state is verified against the repository, not against this view.
* **Czech translation is mine and unreviewed by a native domain reviewer.** 449 distinct texts (703 cells). Review
  `lang/cs.src.json` (EN and CS side by side). Terms deliberately kept in English: Snapshot, Requirement, Evidence, Verdict,
  Provider, adapter (Czech inflection avoided), golden, gate, fingerprint, worktree, fixture.
* Other languages are machine translation done in the reader's browser, if the browser can do it. Verified here: the API object exists,
  the failure paths work. **Not verified: an actual completed machine translation** (the sandbox browser never finished a model download).

## Files

| File | Role |
|---|---|
| `rv_ods.py` | reads the ODS (read-only) into a model: cells, styles as CSS, merges, links, conditional-format colours |
| `rv_text.py` | normalisation, hashing, protected tokens, translation checks |
| `rv_html.py` | renders the page and the language pack (escaping, link policy, CSP) |
| `viewer.js`, `viewer.css` | the page's behaviour and chrome; embedded into the generated HTML |
| `roadmap_view.py` | CLI: `status`, `merge`, `build`, `check` |
| `lang/cs.src.json` | the reviewed Czech source (hash -> EN + CS); `lang/chunks/` holds the batches it was merged from |
| `test_roadmap_view.py`, `test_mutations.py` | invariant tests and negative tests |

## Putting it into the repository

Generated files belong in their own commit/PR, separate from any change to the ODS. The ODS must not appear in that diff.
Before merging, show: the diff, `sha256sum docs/Codelaxy-Roadmap.ods` equal to the banner's SHA-256, `git hash-object` equal to the blob id,
`python roadmap_view.py check` green, and the test run. A tool and its output are tooling: under `docs/branching.md` §6 that is R4.
