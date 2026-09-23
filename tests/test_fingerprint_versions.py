"""Versioned fingerprint bookkeeping (`src/appstate/fingerprint_versions.py`).

Every file this module touches is fabricated in a temp directory and passed
in via `root=` -- never the real repo checkout. The whole point of this
module is that fingerprints are checkout-dependent
(`docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md` E3), so a test that
read `src/`'s actual line endings would pass or fail depending on the
machine it ran on rather than on the code under test.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.appstate import card_ledger, fingerprint_versions as fv


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class TempRepoCase(unittest.TestCase):
    """Base class: one temp directory per test, cleaned up automatically."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class V1ReproducesCodeFingerprintTests(TempRepoCase):
    """V1 is `card_ledger.code_fingerprint`, preserved and callable --
    not a reimplementation that could quietly diverge from it."""

    def test_matches_card_ledger_code_fingerprint_exactly(self):
        _write(self.root, "a.py", b"print('hi')\r\n")
        _write(self.root, "sub/b.json", b'{"x": 1}\n')
        paths = ("a.py", "sub/b.json")

        expected = card_ledger.code_fingerprint(paths, root=str(self.root))
        record = fv.compute_v1(paths, root=str(self.root))

        self.assertEqual(record.value, expected)
        self.assertEqual(record.method, fv.FingerprintMethod.V1_RAW_BYTES)

    def test_matches_on_a_missing_file_too(self):
        # card_ledger.code_fingerprint's sentinel for an absent path
        # (b"<absent>") must behave identically through the new module.
        paths = ("does/not/exist.py",)
        expected = card_ledger.code_fingerprint(paths, root=str(self.root))
        record = fv.compute_v1(paths, root=str(self.root))
        self.assertEqual(record.value, expected)


class V2LineEndingInvarianceTests(TempRepoCase):
    """V2 must be stable across a CRLF/LF-only difference in the same
    committed content -- the exact bug erratum E3 documents."""

    def test_invariant_to_crlf_lf_conversion(self):
        content_lf = b"def f():\n    return 1\n"
        content_crlf = content_lf.replace(b"\n", b"\r\n")
        self.assertNotEqual(content_lf, content_crlf)  # sanity: genuinely different bytes

        lf_root = self.root / "lf"
        crlf_root = self.root / "crlf"
        _write(lf_root, "a.py", content_lf)
        _write(crlf_root, "a.py", content_crlf)
        paths = ("a.py",)

        v2_lf = fv.compute_v2(paths, root=str(lf_root))
        v2_crlf = fv.compute_v2(paths, root=str(crlf_root))
        self.assertEqual(v2_lf.value, v2_crlf.value)

        # And prove this is actually testing something: V1 (raw bytes) MUST
        # differ on the same two checkouts, or the test would pass
        # vacuously even against a V2 that forgot to normalise.
        v1_lf = fv.compute_v1(paths, root=str(lf_root))
        v1_crlf = fv.compute_v1(paths, root=str(crlf_root))
        self.assertNotEqual(v1_lf.value, v1_crlf.value)

    def test_real_content_change_still_moves_v2(self):
        _write(self.root, "a.py", b"return 1\r\n")
        before = fv.compute_v2(("a.py",), root=str(self.root))

        _write(self.root, "a.py", b"return 2\r\n")
        after = fv.compute_v2(("a.py",), root=str(self.root))

        self.assertNotEqual(before.value, after.value)


class ArtifactIdentityTests(TempRepoCase):
    """Runtime artifact identity (frozen params / calibration JSON) must
    ride alongside the combined source fingerprint, not inside it."""

    def test_artifact_identity_present_and_distinguishable(self):
        _write(self.root, "src/report/card_v2.py", b"x = 1\n")
        _write(self.root, "data/processed/card_v2_frozen_params.json",
               b'{"a": 1}\n')
        paths = ("src/report/card_v2.py",
                  "data/processed/card_v2_frozen_params.json")

        record = fv.compute_v1(paths, root=str(self.root))

        self.assertEqual(len(record.artifacts), 1)
        artifact = record.artifacts[0]
        self.assertEqual(artifact.path,
                          "data/processed/card_v2_frozen_params.json")
        # The artifact's own identity is a plain sha256 of its bytes; the
        # combined `value` binds path names and mixes in the other file's
        # bytes too -- they must never collide.
        self.assertNotEqual(artifact.value, record.value)

    def test_non_artifact_paths_produce_no_artifact_entries(self):
        _write(self.root, "src/report/card_v2.py", b"x = 1\n")
        record = fv.compute_v1(("src/report/card_v2.py",), root=str(self.root))
        self.assertEqual(record.artifacts, ())

    def test_artifact_identity_changes_with_content(self):
        rel = "data/processed/card_calibration.json"
        _write(self.root, rel, b'{"a": 1}\n')
        before = fv.artifact_identity(rel, root=str(self.root))
        _write(self.root, rel, b'{"a": 2}\n')
        after = fv.artifact_identity(rel, root=str(self.root))
        self.assertNotEqual(before.value, after.value)


class ClassifierTests(unittest.TestCase):
    """The four owner-named categories, each reached the way it actually
    arises rather than by constructing an artificial VersionedFingerprint
    for its own sake."""

    def _fp(self, value, method=fv.FingerprintMethod.V1_RAW_BYTES, paths=("a.py",)):
        return fv.VersionedFingerprint(value=value, method=method, paths=paths)

    def test_method_change_is_never_content_change(self):
        old = self._fp("deadbeef", method=fv.FingerprintMethod.V1_RAW_BYTES)
        new = self._fp("deadbeef", method=fv.FingerprintMethod.V2_LF_NORMALIZED)
        result = fv.classify_change(old, new)
        self.assertEqual(result.category, fv.ChangeCategory.METHOD_CHANGE)

    def test_representation_only_uses_the_verified_mapping(self):
        crlf_value, mixed_value = fv.REPRESENTATION_ONLY_EQUIVALENCES[0].values
        old = self._fp(crlf_value)
        new = self._fp(mixed_value)
        result = fv.classify_change(old, new)
        self.assertEqual(result.category,
                          fv.ChangeCategory.REPRESENTATION_ONLY)
        self.assertIn("git diff", result.detail)

    def test_real_change_when_not_in_the_mapping(self):
        old = self._fp("1111111111111111111111111111111111111111111111111111111111111111")
        new = self._fp("2222222222222222222222222222222222222222222222222222222222222222")
        result = fv.classify_change(old, new)
        self.assertEqual(result.category, fv.ChangeCategory.REAL_CHANGE)

    def test_selection_behavior_is_always_cannot_determine(self):
        # Even fingerprints that are IDENTICAL must not be read as "so
        # selection behaviour is unchanged" -- a match proves nothing about
        # runtime inputs a hash never saw.
        same = self._fp("cafef00d")
        result = fv.classify_change(same, same, aspect="selection_behavior")
        self.assertEqual(result.category, fv.ChangeCategory.CANNOT_DETERMINE)

        different_old = self._fp("aaaa")
        different_new = self._fp("bbbb")
        result2 = fv.classify_change(different_old, different_new,
                                      aspect="selection_behavior")
        self.assertEqual(result2.category, fv.ChangeCategory.CANNOT_DETERMINE)

    def test_unknown_aspect_rejected(self):
        old = self._fp("aaaa")
        new = self._fp("bbbb")
        with self.assertRaises(ValueError):
            fv.classify_change(old, new, aspect="nonsense")


class V1DiscrepancyIsNotRepresentationOnlyTests(unittest.TestCase):
    """Erratum E4: the section-16 v1_code_fingerprint pins a PRE-COMMIT
    state of two files. That is a real content difference between two
    revisions, and the classifier must never map it as representation-only
    just because it is a "known" mismatch."""

    def test_recorded_discrepancy_registered_as_non_representation(self):
        entry = fv.KNOWN_NON_REPRESENTATION_DISCREPANCIES[0]
        self.assertEqual(
            entry.recorded_value,
            "10f5cac7191ff23d0afcebc1f3566c8e747b9e4286a1eacbbfd8be09bf1c92ee",
        )
        # It must not also appear as one side of a verified equivalence --
        # the two registries name mutually exclusive claims.
        for equivalence in fv.REPRESENTATION_ONLY_EQUIVALENCES:
            self.assertNotIn(entry.recorded_value, equivalence.values)

    def test_classifier_calls_it_a_real_change(self):
        recorded = fv.KNOWN_NON_REPRESENTATION_DISCREPANCIES[0].recorded_value
        # The live-checkout value from the current repo state, per
        # scripts/fingerprint_diagnostic.py's `as_checked_out` for the V1
        # list -- a stand-in "other" value that is NOT the recorded one.
        live_value = "73613c2bf43f5de6217261dcb96b8d2c78dcc90c50c7dac60c597c1a2f13e9d0"

        old = fv.VersionedFingerprint(value=recorded,
                                       method=fv.FingerprintMethod.V1_RAW_BYTES,
                                       paths=card_ledger.V1_FINGERPRINT_FILES)
        new = fv.VersionedFingerprint(value=live_value,
                                       method=fv.FingerprintMethod.V1_RAW_BYTES,
                                       paths=card_ledger.V1_FINGERPRINT_FILES)

        result = fv.classify_change(old, new)
        self.assertEqual(result.category, fv.ChangeCategory.REAL_CHANGE)
        self.assertIn("PRE-COMMIT", result.detail)


class ComparableToTests(unittest.TestCase):
    def test_same_method_is_comparable(self):
        a = fv.VersionedFingerprint(value="x", method=fv.FingerprintMethod.V1_RAW_BYTES, paths=())
        b = fv.VersionedFingerprint(value="y", method=fv.FingerprintMethod.V1_RAW_BYTES, paths=())
        self.assertTrue(a.comparable_to(b))

    def test_different_method_is_not_comparable(self):
        a = fv.VersionedFingerprint(value="x", method=fv.FingerprintMethod.V1_RAW_BYTES, paths=())
        b = fv.VersionedFingerprint(value="x", method=fv.FingerprintMethod.V2_LF_NORMALIZED, paths=())
        self.assertFalse(a.comparable_to(b))


if __name__ == "__main__":
    unittest.main()
