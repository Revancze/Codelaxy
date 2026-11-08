"""IMP2-00 - guard of protected files (tier A). Standard library only."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from clxreg import protect


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git(repo, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", "-C", str(repo), *a],
                          capture_output=True, text=True, check=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)
        self.root = self.d / "ws"
        (self.root / "docs").mkdir(parents=True)
        self.f1 = self.root / "docs" / "a.md"
        self.f1.write_bytes(b"alpha\n")
        self.f2 = self.root / "docs" / "b.md"
        self.f2.write_bytes(b"beta\n")
        (self.root / "docs" / "c.md").write_bytes(b"beta\n")        # a copy: one hash documented for two paths

    def tearDown(self):
        self._t.cleanup()

    def manifest(self, **over):
        m = {"schema": 1, "roots": {"ws": str(self.root)},
             "entries": [{"root": "ws", "path": "docs/a.md", "sha256": sha(b"alpha\n"), "source": "test"},
                         {"root": "ws", "path": "docs/b.md", "sha256": sha(b"beta\n"), "source": "test"}]}
        m.update(over)
        p = self.d / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        return p


class CheckTests(Base):
    def test_unchanged_files_pass(self):
        self.assertEqual(protect.check(self.manifest()), [])

    def test_changed_byte_is_reported_by_name(self):
        self.f1.write_bytes(b"alphA\n")
        f = protect.check(self.manifest())
        self.assertEqual([(x.code, x.record) for x in f], [("PR-02", "ws:docs/a.md")])

    def test_missing_file_is_reported(self):
        self.f2.unlink()
        f = protect.check(self.manifest())
        self.assertEqual([(x.code, x.record) for x in f], [("PR-01", "ws:docs/b.md")])

    def test_zero_entries_is_an_error_not_a_pass(self):
        f = protect.check(self.manifest(entries=[]))
        self.assertEqual([x.code for x in f], ["PR-04"])

    def test_unknown_root_is_an_error(self):
        m = self.manifest()
        d = json.loads(m.read_text(encoding="utf-8"))
        d["entries"][0]["root"] = "nope"
        m.write_text(json.dumps(d), encoding="utf-8")
        self.assertIn("PR-04", [x.code for x in protect.check(m)])

    def test_unknown_schema_is_an_error_even_if_everything_else_is_valid(self):
        m = self.manifest(schema=2)
        self.assertEqual([x.code for x in protect.check(m)], ["PR-04"])

    def test_malformed_hash_is_an_invalid_entry_not_a_mismatch(self):
        m = self.manifest()
        d = json.loads(m.read_text(encoding="utf-8"))
        d["entries"][0]["sha256"] = "ABC"
        m.write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual([x.code for x in protect.check(m)], ["PR-04"])

    def test_root_can_be_remapped(self):
        other = self.d / "copy"
        (other / "docs").mkdir(parents=True)
        (other / "docs" / "a.md").write_bytes(b"alpha\n")
        (other / "docs" / "b.md").write_bytes(b"beta\n")
        m = self.manifest(roots={"ws": str(self.d / "does-not-exist")})      # without the override every file is missing
        self.assertEqual([x.code for x in protect.check(m)], ["PR-01", "PR-01"])
        self.assertEqual(protect.check(m, root_overrides={"ws": str(other)}), [])

    def test_entry_must_not_escape_its_root(self):
        m = self.manifest()
        d = json.loads(m.read_text(encoding="utf-8"))
        d["entries"][0]["path"] = "../outside.txt"
        m.write_text(json.dumps(d), encoding="utf-8")
        self.assertIn("PR-04", [x.code for x in protect.check(m)])


class StagedTests(Base):
    def test_nothing_staged_passes_and_staged_fails(self):
        repo = self.d / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        (repo / "x.txt").write_text("1", encoding="utf-8")
        self.assertEqual(protect.check_staged(repo), [])
        git(repo, "add", "x.txt")
        f = protect.check_staged(repo)
        self.assertEqual([x.code for x in f], ["PR-03"])
        self.assertIn("x.txt", f[0].message)

    def test_not_a_repo_is_an_error(self):
        self.assertEqual([x.code for x in protect.check_staged(self.d / "ws")], ["PR-04"])


class BuildTests(Base):
    INV = "text\n```text\n{h1}  docs/a.md\n{h2}  docs/b.md; docs/c.md  (comment)\n```\n"

    def inv(self, h1=None, h2=None):
        p = self.d / "INVENTORY.md"
        p.write_text(self.INV.format(h1=h1 or sha(b"alpha\n"), h2=h2 or sha(b"beta\n")), encoding="utf-8")
        return p

    def test_build_from_documented_hashes(self):
        out = self.d / "built.json"
        m = protect.build_from_inventory(self.inv(), {"docs/": "ws"}, {"ws": str(self.root)}, out)
        self.assertEqual(protect.check(out), [])
        self.assertEqual(len(m["entries"]), 3)           # one hash documented for two paths (copies)
        self.assertTrue(all(e["source"] == "inventory" for e in m["entries"]))

    def test_build_refuses_when_disk_differs_from_documented_hash(self):
        out = self.d / "built.json"
        with self.assertRaises(protect.BuildError) as cm:
            protect.build_from_inventory(self.inv(h1="0" * 64), {"docs/": "ws"}, {"ws": str(self.root)}, out)
        self.assertIn("docs/a.md", str(cm.exception))
        self.assertFalse(out.exists())

    def test_build_refuses_to_overwrite_and_unmapped_paths(self):
        out = self.d / "built.json"
        out.write_text("{}", encoding="utf-8")
        with self.assertRaises(protect.BuildError):
            protect.build_from_inventory(self.inv(), {"docs/": "ws"}, {"ws": str(self.root)}, out)
        out.unlink()
        with self.assertRaises(protect.BuildError):
            protect.build_from_inventory(self.inv(), {"other/": "ws"}, {"ws": str(self.root)}, out)


class CliTests(Base):
    def test_exit_codes(self):
        m = self.manifest()
        self.assertEqual(protect.main(["check", "--manifest", str(m)]), 0)
        self.f1.write_bytes(b"x")
        self.assertEqual(protect.main(["check", "--manifest", str(m)]), 1)


if __name__ == "__main__":
    unittest.main()
