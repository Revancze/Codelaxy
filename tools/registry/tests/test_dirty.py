"""IMP2-11 (a) - fingerprint of a DIRTY working tree: what differs from HEAD, by content, never by time or order (tier A)."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from clxreg import canon, dirty
from tests.test_store import commit_all, git


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.repo = Path(self._t.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.w("a.txt", b"alpha\n")
        self.w("dir/b.txt", b"beta\n")
        self.w(".gitignore", b"bin/\nobj/\n*.log\n")
        commit_all(self.repo, "base")
        self.head = git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def w(self, rel, data):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def m(self):
        return dirty.git_dirty_manifest(self.repo)

    def d(self):
        return dirty.digest(self.m())


class GitDirtyTests(RepoCase):
    def test_a_clean_tree_has_an_empty_manifest_bound_to_head(self):
        m = self.m()
        self.assertEqual((m["kind"], m["head"], m["changed"], m["deleted"], m["untracked"]), ("git-dirty", self.head, [], [], []))

    def test_digest_is_stable(self):
        self.assertEqual(self.d(), self.d())

    def test_a_changed_byte_a_new_untracked_file_and_a_deleted_file_each_change_the_fingerprint(self):
        base = self.d()
        seen = {base}
        self.w("a.txt", b"alpha!\n")
        self.assertNotIn(self.d(), seen)
        seen.add(self.d())
        self.w("new.txt", b"new\n")
        self.assertNotIn(self.d(), seen)
        seen.add(self.d())
        (self.repo / "dir" / "b.txt").unlink()
        self.assertNotIn(self.d(), seen)
        m = self.m()
        self.assertEqual([c["path"] for c in m["changed"]], ["a.txt"])
        self.assertEqual(m["deleted"], ["dir/b.txt"])
        self.assertEqual([c["path"] for c in m["untracked"]], ["new.txt"])

    def test_the_hash_is_of_the_working_tree_bytes(self):
        import hashlib
        self.w("new.txt", b"new\n")
        self.assertEqual(self.m()["untracked"][0]["sha256"], hashlib.sha256(b"new\n").hexdigest())

    def test_changing_the_time_of_a_file_does_not_change_the_fingerprint(self):
        p = self.w("a.txt", b"alpha!\n")
        before = self.d()
        os.utime(p, (1_000_000_000, 1_000_000_000))
        self.assertEqual(self.d(), before)

    def test_the_order_files_were_created_in_does_not_matter(self):
        self.w("x1.txt", b"1")
        self.w("x2.txt", b"2")
        self.w("x3.txt", b"3")
        one = self.d()
        for n in ("x1", "x2", "x3"):
            (self.repo / f"{n}.txt").unlink()
        for n in ("x3", "x1", "x2"):
            self.w(f"{n}.txt", n[1:].encode())
        self.assertEqual(self.d(), one)

    def test_ignored_build_output_is_not_part_of_the_fingerprint(self):
        before = self.d()
        self.w("bin/Debug/out.dll", b"binary")
        self.w("obj/x.cache", b"cache")
        self.w("run.log", b"log")
        self.assertEqual(self.d(), before)

    def test_staged_and_unstaged_changes_give_the_same_content_fingerprint(self):
        self.w("a.txt", b"alpha!\n")
        unstaged = self.m()["changed"]
        git(self.repo, "add", "a.txt")
        self.assertEqual(self.m()["changed"], unstaged)

    def test_a_staged_rename_is_still_a_deletion_and_an_addition(self):
        git(self.repo, "mv", "a.txt", "a2.txt")
        m = self.m()
        self.assertEqual(([c["path"] for c in m["changed"]], m["deleted"]), (["a2.txt"], ["a.txt"]))

    def test_a_rename_is_a_deletion_and_an_addition_not_a_hidden_move(self):
        (self.repo / "a.txt").rename(self.repo / "a2.txt")
        m = self.m()
        self.assertEqual((m["deleted"], [c["path"] for c in m["untracked"]]), (["a.txt"], ["a2.txt"]))

    def test_reverting_a_change_restores_the_fingerprint(self):
        base = self.d()
        self.w("a.txt", b"other\n")
        self.assertNotEqual(self.d(), base)
        self.w("a.txt", b"alpha\n")
        self.assertEqual(self.d(), base)

    def test_line_endings_are_part_of_the_content(self):
        self.w("a.txt", b"alpha\r\n")
        crlf = self.d()
        self.w("a.txt", b"alpha\n")
        self.assertNotEqual(self.d(), crlf)

    def test_non_ascii_paths(self):
        self.w("dir/ář.txt", b"x")
        self.assertEqual([c["path"] for c in self.m()["untracked"]], ["dir/ář.txt"])

    def test_paths_are_sorted_by_code_point(self):
        for n in ("b.txt", "B.txt", "a/z.txt", "a.txt2"):
            self.w(n, b"x")
        paths = [c["path"] for c in self.m()["untracked"]]
        self.assertEqual(paths, sorted(paths))

    def test_the_head_is_part_of_the_fingerprint(self):
        self.w("a.txt", b"alpha!\n")
        d1 = self.d()
        commit_all(self.repo, "second")
        self.w("a.txt", b"alpha!!\n")
        self.assertNotEqual(self.d(), d1)

    def test_the_manifest_is_canonical_data(self):
        self.w("new.txt", b"x")
        self.assertTrue(canon.is_canonical(canon.dumps(self.m())))

    def test_not_a_repository_and_a_repository_without_commits_are_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(dirty.ManifestError):
                dirty.git_dirty_manifest(d)
            git(Path(d), "init", "-q")
            with self.assertRaises(dirty.ManifestError):
                dirty.git_dirty_manifest(d)

    def test_git_output_is_sorted_by_us_not_trusted_to_be_sorted(self):
        from unittest import mock
        self.w("b.txt", b"b")
        self.w("a.txt", b"a")
        real = dirty._git

        def fake(repo, *args):
            if args[:1] == ("diff",):
                return b"M\0b.txt\0M\0a.txt\0D\0dir/b.txt\0D\0README.gone\0"
            if args[:1] == ("ls-files",):
                return b"z.txt\0y.txt\0"
            return real(repo, *args)

        self.w("y.txt", b"y")
        self.w("z.txt", b"z")
        with mock.patch.object(dirty, "_git", fake):
            m = dirty.git_dirty_manifest(self.repo)
        self.assertEqual(([c["path"] for c in m["changed"]], [c["path"] for c in m["untracked"]]), (["a.txt", "b.txt"], ["y.txt", "z.txt"]))
        self.assertEqual(m["deleted"], ["README.gone", "dir/b.txt"])

    def test_a_file_that_vanished_between_listing_and_hashing_is_reported_as_deleted(self):
        from unittest import mock
        real = dirty._git

        def fake(repo, *args):
            return b"M\0ghost.txt\0" if args[:1] == ("diff",) else real(repo, *args)

        with mock.patch.object(dirty, "_git", fake):
            m = dirty.git_dirty_manifest(self.repo)
        self.assertEqual((m["changed"], m["deleted"]), ([], ["ghost.txt"]))

    def test_unexpected_git_output_is_an_error(self):
        from unittest import mock
        real = dirty._git

        def fake(repo, *args):
            return b"M\0" if args[:1] == ("diff",) else real(repo, *args)

        with mock.patch.object(dirty, "_git", fake):
            with self.assertRaises(dirty.ManifestError):
                dirty.git_dirty_manifest(self.repo)

    def test_an_untracked_nested_repository_is_an_error_not_a_silent_gap(self):
        nested = self.repo / "vendor" / "lib"
        nested.mkdir(parents=True)
        git(nested, "init", "-q")
        (nested / "f.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(dirty.ManifestError):
            self.m()

    def test_a_path_that_is_not_valid_utf8_is_an_error(self):
        from unittest import mock
        real = dirty._git

        def fake(repo, *args):
            return b"\xff\xfe.txt\0" if args[:1] == ("ls-files",) else real(repo, *args)

        with mock.patch.object(dirty, "_git", fake):
            with self.assertRaises(dirty.ManifestError) as cm:
                dirty.git_dirty_manifest(self.repo)
        self.assertIn("UTF-8", str(cm.exception))

    def test_nothing_is_changed_or_staged_by_reading(self):
        self.w("a.txt", b"alpha!\n")
        self.w("new.txt", b"x")
        before = git(self.repo, "status", "--porcelain").stdout
        self.m()
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, before)
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only").stdout, "")

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_a_symbolic_link_is_refused_as_an_unbounded_input(self):
        outside = Path(self._t.name) / "outside.txt"
        outside.write_bytes(b"secret")
        try:
            os.symlink(outside, self.repo / "link")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted here")
        with self.assertRaises(dirty.ManifestError):
            self.m()


class TreeManifestTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name) / "copy"
        self.root.mkdir()
        self.w("a.txt", b"a")
        self.w("src/b.cs", b"b")

    def w(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def m(self, **kw):
        return dirty.tree_manifest(self.root, **kw)

    def test_all_files_with_hashes_and_the_declared_exclusions(self):
        m = self.m()
        self.assertEqual((m["kind"], [f["path"] for f in m["files"]], m["excludes"]), ("tree", ["a.txt", "src/b.cs"], ["bin", "obj"]))

    def test_build_output_at_any_depth_is_excluded_and_the_exclusion_is_recorded(self):
        before = dirty.digest(self.m())
        self.w("bin/x.dll", b"1")
        self.w("src/obj/y.o", b"2")
        self.w("src/deep/bin/z", b"3")
        self.assertEqual(dirty.digest(self.m()), before)

    def test_the_exclusions_are_part_of_the_digest(self):
        self.assertNotEqual(dirty.digest(self.m()), dirty.digest(self.m(excludes=())))

    def test_a_file_named_like_an_excluded_directory_is_not_excluded(self):
        self.w("bin", b"i am a file")
        self.assertIn("bin", [f["path"] for f in self.m()["files"]])

    def test_the_git_directory_is_never_part_of_it(self):
        before = dirty.digest(self.m())
        self.w(".git/HEAD", b"ref")
        self.assertEqual(dirty.digest(self.m()), before)

    def test_content_name_addition_and_deletion_change_it(self):
        base = dirty.digest(self.m())
        for step in (lambda: self.w("a.txt", b"A"), lambda: self.w("c.txt", b"c"), lambda: (self.root / "c.txt").unlink()):
            step()
            now = dirty.digest(self.m())
            self.assertNotEqual(now, base)
            base = now
        (self.root / "a.txt").rename(self.root / "a2.txt")
        self.assertNotEqual(dirty.digest(self.m()), base)

    def test_time_and_creation_order_do_not_matter(self):
        d1 = dirty.digest(self.m())
        os.utime(self.root / "a.txt", (1_000_000_000, 1_000_000_000))
        self.assertEqual(dirty.digest(self.m()), d1)
        shutil.rmtree(self.root)
        self.root.mkdir()
        self.w("src/b.cs", b"b")
        self.w("a.txt", b"a")
        self.assertEqual(dirty.digest(self.m()), d1)

    def test_files_come_out_sorted_whatever_order_the_file_system_lists_them_in(self):
        from unittest import mock
        real = os.walk

        def reversed_walk(top, followlinks=False, onerror=None):
            for dirpath, dirnames, filenames in real(top, followlinks=followlinks, onerror=onerror):
                yield dirpath, dirnames, sorted(filenames, reverse=True)

        self.w("z.txt", b"z")
        self.w("m.txt", b"m")
        with mock.patch.object(dirty.os, "walk", reversed_walk):
            paths = [f["path"] for f in self.m()["files"]]
        self.assertEqual(paths, sorted(paths))

    def test_a_git_link_file_is_never_part_of_it(self):
        before = dirty.digest(self.m())
        self.w(".git", b"gitdir: /elsewhere")
        self.assertEqual(dirty.digest(self.m()), before)

    def test_the_order_of_the_exclusions_does_not_matter(self):
        self.assertEqual(dirty.digest(self.m(excludes=("obj", "bin"))), dirty.digest(self.m(excludes=("bin", "obj"))))
        self.assertEqual(self.m(excludes=("obj", "bin", "bin"))["excludes"], ["bin", "obj"])

    def test_paths_are_posix_on_every_platform(self):
        self.assertTrue(all("\\" not in f["path"] for f in self.m()["files"]))

    def test_a_missing_root_is_an_error(self):
        with self.assertRaises(dirty.ManifestError):
            dirty.tree_manifest(self.root / "nope")


if __name__ == "__main__":
    unittest.main()
