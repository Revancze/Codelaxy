"""IMP2-12 - currency of evidence (Q8 from git) and propagation of a changed contract through `depends_on_revisions` (tier A)."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clxreg import freshness as fr
from tests.test_store import commit_all, git


class Repo(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.repo = Path(self._t.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.w("src/a.cs", "a")
        self.w("src/sub/b.cs", "b")
        self.w("docs/x.md", "x")
        self.w("README.md", "r")
        self.c0 = self.commit("base")

    def w(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def commit(self, msg):
        commit_all(self.repo, msg)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def a(self, commit=None, scope=("src/**",), ref=None):
        return fr.assess(self.repo, commit or self.c0, ref, scope)


class GlobTests(unittest.TestCase):
    def test_masks(self):
        m = fr.matches
        self.assertTrue(m("src/a.cs", "src/**"))
        self.assertTrue(m("src/sub/deep/b.cs", "src/**"))
        self.assertFalse(m("srcx/a.cs", "src/**"))
        self.assertTrue(m("src/a.cs", "src/*.cs"))
        self.assertFalse(m("src/sub/b.cs", "src/*.cs"))
        self.assertTrue(m("src/sub/b.cs", "**/b.cs"))
        self.assertTrue(m("b.cs", "**/b.cs"))
        self.assertTrue(m("src/a.cs", "src/?.cs"))
        self.assertFalse(m("src/ab.cs", "src/?.cs"))
        self.assertTrue(m("src/a.cs", "src/a.cs"))
        self.assertFalse(m("src/a.cs2", "src/a.cs"))
        self.assertTrue(m("src/sub/b.cs", "src/sub"))            # a plain directory name covers what is under it
        self.assertFalse(m("src/subx/b.cs", "src/sub"))
        self.assertTrue(m("src/sub/b.cs", "src/sub/"))
        self.assertFalse(m("src/sub", "src/sub/"))
        self.assertFalse(m("src/sub/", "src/sub/"))              # the directory itself is not part of what is under it
        self.assertFalse(m("src/a.cs", "src?a.cs"))               # ? never stands for a separator
        self.assertTrue(m("srcxa.cs", "src?a.cs"))
        self.assertTrue(m("a (1)+[x].cs", "a (1)+[x].cs"))        # regex characters are literal
        self.assertFalse(m("src/a.cs", ":(top)src"))               # no git pathspec magic

    def test_bad_masks_are_errors(self):
        for bad in ("", "/etc", "../x", "a/../b", "a\\b", "a\0b", None, 3):
            with self.assertRaises(fr.FreshnessError, msg=repr(bad)):
                fr.matches("x", bad)


class AssessTests(Repo):
    def test_the_evidence_commit_itself_is_current_even_without_scope(self):
        self.assertEqual(self.a(scope=()).state, "CURRENT")
        self.assertEqual(self.a(scope=None).state, "CURRENT")

    def test_a_later_commit_touching_only_other_paths_leaves_it_current(self):
        self.w("docs/x.md", "x2")
        self.commit("docs")
        r = self.a()
        self.assertEqual((r.state, r.changed), ("CURRENT", ()))

    def test_a_change_inside_the_scope_makes_it_stale_and_names_the_files(self):
        self.w("src/a.cs", "a2")
        self.w("docs/x.md", "x2")
        self.commit("code")
        r = self.a()
        self.assertEqual((r.state, r.changed), ("STALE", ("src/a.cs",)))

    def test_without_scope_any_later_commit_makes_it_stale(self):
        self.w("docs/x.md", "x2")
        self.commit("docs")
        for scope in ((), None):
            self.assertEqual(self.a(scope=scope).state, "STALE")

    def test_a_rename_out_of_the_scope_and_into_it_are_both_changes(self):
        (self.repo / "src" / "a.cs").rename(self.repo / "docs" / "a.cs")
        self.commit("move out")
        self.assertEqual(self.a().state, "STALE")
        (self.repo / "docs" / "a.cs").rename(self.repo / "docs" / "a2.cs")
        c1 = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.commit("rename outside")
        self.assertEqual(self.a(commit=c1).state, "CURRENT")
        (self.repo / "docs" / "a2.cs").rename(self.repo / "src" / "back.cs")
        self.commit("move in")
        r = self.a(commit=c1)
        self.assertEqual((r.state, r.changed), ("STALE", ("src/back.cs",)))

    def test_a_change_that_is_reverted_is_no_net_change(self):
        self.w("src/a.cs", "a2")
        self.commit("change")
        self.w("src/a.cs", "a")
        self.commit("revert")
        self.assertEqual(self.a().state, "CURRENT")

    def test_the_reference_can_be_given_and_defaults_to_head(self):
        self.w("src/a.cs", "a2")
        c1 = self.commit("code")
        self.assertEqual(self.a(ref=self.c0).state, "CURRENT")
        self.assertEqual(self.a(ref=c1).state, "STALE")
        self.assertEqual(self.a(ref="HEAD").state, "STALE")

    def test_an_unreachable_commit_is_undetermined_and_advisory_ad09(self):
        r = self.a(commit="ab" * 20)
        self.assertEqual(r.state, "UNDETERMINED")
        self.assertEqual([(f.cls, f.code) for f in r.findings], [("ADVISORY", "AD-09")])

    def test_a_commit_that_is_not_an_ancestor_is_undetermined(self):
        git(self.repo, "checkout", "-q", "-b", "other", self.c0)
        self.w("src/o.cs", "o")
        other = self.commit("other")
        git(self.repo, "checkout", "-q", "main")
        self.w("docs/x.md", "x3")
        self.commit("main moves")
        r = self.a(commit=other)
        self.assertEqual(r.state, "UNDETERMINED")
        self.assertIn("ancestor", r.reason)

    def test_a_commit_that_is_not_a_full_hash_is_undetermined(self):
        for c in (self.c0[:7], "HEAD", "", None, self.c0.upper()):
            r = fr.assess(self.repo, c, None, ["src/**"])
            self.assertEqual(r.state, "UNDETERMINED", repr(c))

    def test_a_bad_reference_or_repository_is_an_error_not_a_verdict(self):
        with self.assertRaises(fr.FreshnessError):
            fr.assess(self.repo, self.c0, "no-such-ref", ["src/**"])
        with self.assertRaises(fr.FreshnessError):
            fr.assess(self.repo, self.c0, "--output=x", ["src/**"])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(fr.FreshnessError):
                fr.assess(d, self.c0, None, ["src/**"])

    def _with_git(self, wrong):
        """fr._git, except that the git call whose first arguments are `wrong` (a prefix) gives the prepared answer."""
        real = fr._git
        prefix, answer = wrong

        def fake(repo, *args):
            if args[:len(prefix)] == prefix:
                return answer
            return real(repo, *args)

        return mock.patch.object(fr, "_git", fake)

    def test_a_git_failure_while_asking_for_ancestry_is_an_error_not_a_verdict(self):
        self.w("docs/x.md", "x2")
        self.commit("docs")
        for code in (128, 2):
            with self._with_git((("merge-base",), subprocess.CompletedProcess([], code, b"", b"boom"))):
                with self.assertRaises(fr.FreshnessError):
                    self.a()

    def test_a_reference_that_git_resolves_to_something_that_is_not_a_full_hash_is_refused(self):
        for answer in (b"abc\n", b"\n", b"A" * 40 + b"\n"):
            with self._with_git((("rev-parse",), subprocess.CompletedProcess([], 0, answer, b""))):
                with self.assertRaises(fr.FreshnessError) as cm:
                    fr._resolve(self.repo, "HEAD")
            self.assertIn("is not a commit", str(cm.exception))
        self.assertEqual(fr._resolve(self.repo, "HEAD"), self.c0)

    def test_bad_masks_in_scope_are_errors(self):
        with self.assertRaises(fr.FreshnessError):
            self.a(scope=["../x"])

    def test_paths_with_spaces_and_non_ascii_characters(self):
        self.w("src/a b/á.cs", "1")
        c1 = self.commit("add")
        self.w("src/a b/á.cs", "2")
        self.commit("change")
        r = self.a(commit=c1)
        self.assertEqual(r.changed, ("src/a b/á.cs",))

    def test_assessment_changes_and_stages_nothing(self):
        self.w("src/a.cs", "a2")
        self.commit("code")
        self.w("docs/x.md", "dirty")
        before = git(self.repo, "status", "--porcelain").stdout
        self.a()
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, before)
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only").stdout, "")

    def test_a_repository_in_a_subdirectory_is_found_from_the_given_path(self):
        self.assertEqual(self.a().state, "CURRENT")
        r = fr.assess(self.repo / "src", self.c0, None, ["src/**"])
        self.assertEqual(r.state, "CURRENT")


class DependencyTests(unittest.TestCase):
    def test_a_raised_revision_of_a_dependency_makes_the_evidence_stale(self):
        self.assertEqual(fr.check_dependencies({"CLX-REQ-0010": 1}, {"CLX-REQ-0010": 2}).state, "STALE")
        self.assertEqual(fr.check_dependencies({"CLX-REQ-0010": 1}, {"CLX-REQ-0010": 1}).state, "CURRENT")

    def test_all_dependencies_count_and_staleness_names_them(self):
        r = fr.check_dependencies({"A": 1, "B": 1, "C": 3}, {"A": 1, "B": 2, "C": 4})
        self.assertEqual((r.state, r.changed), ("STALE", ("B", "C")))

    def test_a_dependency_that_is_unknown_now_or_went_backwards_is_undetermined(self):
        self.assertEqual(fr.check_dependencies({"A": 1}, {}).state, "UNDETERMINED")
        self.assertEqual(fr.check_dependencies({"A": 2}, {"A": 1}).state, "UNDETERMINED")

    def test_stale_beats_undetermined(self):
        self.assertEqual(fr.check_dependencies({"A": 1, "B": 1}, {"A": 2}).state, "STALE")

    def test_no_snapshot_means_nothing_is_claimed_about_contracts(self):
        for snap in (None, {}):
            r = fr.check_dependencies(snap, {"A": 9})
            self.assertEqual((r.state, r.changed), ("CURRENT", ()))
            self.assertIn("not modelled", r.reason)

    def test_malformed_snapshots_are_undetermined(self):
        for snap in ({"A": "1"}, {"A": True}, {"A": 0}, {1: 1}, []):
            self.assertEqual(fr.check_dependencies(snap, {"A": 1}).state, "UNDETERMINED", repr(snap))

    def test_combine_takes_the_worst_proven_state(self):
        mk = lambda s: fr.Freshness(s, "", (), ())       # noqa: E731
        self.assertEqual(fr.combine(mk("CURRENT"), mk("CURRENT")).state, "CURRENT")
        self.assertEqual(fr.combine(mk("CURRENT"), mk("UNDETERMINED")).state, "UNDETERMINED")
        self.assertEqual(fr.combine(mk("UNDETERMINED"), mk("STALE")).state, "STALE")
        self.assertEqual(fr.combine(mk("STALE"), mk("CURRENT")).state, "STALE")

    def test_a_contract_change_propagates_only_to_the_evidence_that_depends_on_it(self):
        evidences = {"EVD-1": {"depends_on_revisions": {"Contracts": 1}}, "EVD-2": {"depends_on_revisions": {"Contracts": 2, "Other": 1}},
                     "EVD-3": {"depends_on_revisions": {"Other": 1}}, "EVD-4": {}}
        out = fr.propagate(evidences, {"Contracts": 2, "Other": 1})
        self.assertEqual({k: v.state for k, v in out.items()}, {"EVD-1": "STALE", "EVD-2": "CURRENT", "EVD-3": "CURRENT", "EVD-4": "CURRENT"})

    def test_inputs_are_not_modified(self):
        snap, cur = {"A": 1}, {"A": 2}
        fr.check_dependencies(snap, cur)
        self.assertEqual((snap, cur), ({"A": 1}, {"A": 2}))


class EndToEndTests(Repo):
    def test_the_combined_state_feeds_the_evidence_derivation(self):
        from clxreg import evidence as ev
        from tests.test_evidence import evd, req, scn
        e = evd(subject={"repository": "r", "commit": self.c0, "tree_state": "CLEAN"})
        r = req(persistence="CONTINUOUS")
        s = {"CLX-SCN-0001": scn()}
        cur = fr.combine(self.a(), fr.check_dependencies({"Contracts": 1}, {"Contracts": 1}))
        self.assertEqual(ev.derive(r, s, {"CLX-EVD-0001": e}, {"freshness": {"CLX-EVD-0001": cur.state}}).verification, "VERIFIED")
        self.w("src/a.cs", "changed")
        self.commit("code")
        stale = fr.combine(self.a(), fr.check_dependencies({"Contracts": 1}, {"Contracts": 1}))
        self.assertEqual(ev.derive(r, s, {"CLX-EVD-0001": e}, {"freshness": {"CLX-EVD-0001": stale.state}}).verification, "STALE")
        contract = fr.combine(self.a(commit=git(self.repo, "rev-parse", "HEAD").stdout.strip()), fr.check_dependencies({"Contracts": 1}, {"Contracts": 2}))
        self.assertEqual(contract.state, "STALE")


if __name__ == "__main__":
    unittest.main()
