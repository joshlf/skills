"""Public-only structural checks; never invoke a model or load private fixtures."""
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {'clear-writing': 'clear-writing', 'commit-message': 'commit-message',
            'model-refinement': 'model-refinement', 'robust-code': 'robust-code',
            'skill-authorship': 'skill-authorship',
            'reader-oriented-explanation': 'reader-oriented-explanation',
            'authorship_disclosure': 'authorship-disclosure'}


class Packages(unittest.TestCase):
    def test_exact_package_set_and_names(self):
        actual = {p.parent.name for p in ROOT.glob('*/SKILL.md')}
        self.assertEqual(actual, set(PACKAGES))
        for folder, name in PACKAGES.items():
            value = (ROOT/folder/'SKILL.md').read_text()
            self.assertTrue(value.startswith('---\n'))
            self.assertIn('\nname: '+name+'\n', value)
            self.assertRegex(value, r'(?m)^description:')

    def test_complete_supporting_resources_and_safe_relative_links(self):
        for package in PACKAGES:
            for file in (ROOT/package).rglob('*.md'):
                self.assertFalse(file.is_symlink())
                for target in re.findall(r'\]\(([^\s)]+)\)', file.read_text()):
                    url = urlsplit(target)
                    if url.scheme or url.netloc: continue
                    if not url.path: continue
                    resolved = (file.parent/unquote(url.path)).resolve()
                    self.assertIn(ROOT, resolved.parents)
                    self.assertTrue(resolved.exists(), str(file.relative_to(ROOT)))

    def test_no_private_directories_or_license_files(self):
        for name in ['development', 'publication', 'public-docs']:
            self.assertFalse((ROOT/name).exists())
        for file in ROOT.rglob('*'):
            if '.git' not in file.relative_to(ROOT).parts:
                self.assertFalse(re.match(r'licen[cs]e(?:[._-]|$)', file.name, re.I))


if __name__ == '__main__': unittest.main()
