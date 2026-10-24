"""Canonicalize only owned fixture roots; operator path validation stays strict."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.observation_validation import regular
import test_grant_broker as fixtures


class FixturePathTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve(strict=True)
        self.canonical_parent = self.root/'private'/'var'/'folders'
        self.canonical_parent.mkdir(parents=True)
        (self.root/'var').symlink_to('private/var', target_is_directory=True)
        self.alias_parent = self.root/'var'/'folders'

    def private_file(self, root):
        path = root/'policy.json'
        path.write_text('{}')
        path.chmod(0o600)
        return path

    def test_canonical_private_var_layout_passes_and_raw_alias_stays_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.alias_parent) as directory:
            raw = Path(directory)
            canonical = raw.resolve(strict=True)
            self.assertNotEqual(raw, canonical)
            self.assertTrue(canonical.is_relative_to(self.canonical_parent))
            path = self.private_file(canonical)
            self.assertEqual(regular(path), path)
            with self.assertRaisesRegex(ValueError, 'Symlink destination rejected'):
                regular(raw/path.name)

    def test_unexpected_directory_and_file_symlinks_stay_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.canonical_parent) as directory:
            root = Path(directory).resolve(strict=True)
            path = self.private_file(root)
            (self.root/'unexpected').symlink_to(root, target_is_directory=True)
            (root/'linked-policy.json').symlink_to(path)
            for untrusted in (self.root/'unexpected'/path.name, root/'linked-policy.json'):
                with self.subTest(path=untrusted), self.assertRaisesRegex(ValueError, 'Symlink destination rejected'):
                    regular(untrusted)
            self.assertEqual(regular(path), path)

    def test_shared_broker_fixture_canonicalizes_roots_before_policy_and_ledger_creation(self):
        original = tempfile.TemporaryDirectory
        def aliased_directory(*args, **kwargs):
            self.assertNotIn('dir', kwargs)
            return original(*args, dir=self.alias_parent, **kwargs)
        # Model the macOS default across the nested coordinator/catalog/runner fixtures.
        with patch.object(tempfile, 'TemporaryDirectory', side_effect=aliased_directory):
            fixture = fixtures.Fixture()
        self.addCleanup(fixture.close)
        for root in (fixture.f.root, fixture.controller.root):
            self.assertEqual(root, root.resolve(strict=True))
            self.assertTrue(root.is_relative_to(self.canonical_parent))
        claim = fixture.claim()
        self.assertEqual(fixture.broker.inspect()['tasks'][claim['execution']]['state'], 'claimed')
        self.assertEqual(regular(fixture.controller.path), fixture.controller.path)
        self.assertEqual(regular(fixture.broker.path), fixture.broker.path)

    @unittest.skipUnless(sys.platform == 'darwin', 'Native /private/var ancestry requires macOS')
    def test_native_macos_private_var_fixture_root(self):
        # /var/tmp is writable on macOS and traverses the same /var alias as /var/folders.
        with tempfile.TemporaryDirectory(dir='/var/tmp') as directory:
            raw = Path(directory)
            canonical = raw.resolve(strict=True)
            self.assertTrue(canonical.is_relative_to('/private/var'))
            path = self.private_file(canonical)
            self.assertEqual(regular(path), path)
            with self.assertRaisesRegex(ValueError, 'Symlink destination rejected'):
                regular(raw/path.name)


if __name__ == '__main__':
    unittest.main()
