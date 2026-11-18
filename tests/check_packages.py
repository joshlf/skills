"""Public-only structural checks; never load private fixtures or execute skills."""
import importlib.util
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'public_skill_packages', ROOT/'tools/skill_packages.py')
packages = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = packages
_spec.loader.exec_module(packages)
PACKAGES = {'clear-writing': 'clear-writing', 'commit-message': 'commit-message',
            'model-refinement': 'model-refinement', 'robust-code': 'robust-code',
            'skill-authorship': 'skill-authorship',
            'reader-oriented-explanation': 'reader-oriented-explanation',
            'authorship_disclosure': 'authorship-disclosure'}


def require(condition, message):
    if not condition:
        raise packages.Invalid(message)


def artifacts(root):
    """Inspect every present declared runtime; source comparison detects omission."""
    result = []
    for name in PACKAGES:
        artifact = packages.describe(packages.capture_directory(root/name), name)
        require(artifact.kind == 'standalone', 'Expected standalone skill')
        description = artifact.skills[0].description
        require(description is not None and bool(description.strip())
                and len(description) <= 1024, 'Missing public skill description')
        result.append((root/name, artifact))
    systems = root/'systems'
    if systems.exists() or systems.is_symlink():
        require(systems.is_dir() and not systems.is_symlink(),
                         'Invalid systems namespace')
        for system in sorted(systems.iterdir()):
            packages.path_name(system.name)
            require(not system.name.startswith('.') and not system.is_symlink(),
                    'Invalid system container')
            if not system.is_dir():
                continue
            runtime = system/'runtime'
            if not runtime.exists() and not runtime.is_symlink():
                continue
            artifact = packages.describe(packages.capture_directory(runtime), 'runtime')
            require(artifact.kind == 'native', 'Expected native runtime')
            packages.plan_intact(artifact)
            result.append((runtime, artifact))
    owned = {package_root/name for package_root, artifact in result
             for name in artifact.files}
    require(all(path in owned for path in root.rglob('*')
                if '.git' not in path.relative_to(root).parts
                and path.name.casefold() in {'skill.md', 'plugin.json'}),
            'Package marker outside a supported artifact')
    packages.validate_namespace([artifact for _, artifact in result])
    return tuple(result)


class Packages(unittest.TestCase):
    def test_exact_package_set_and_names(self):
        actual = {p.parent.name for p in ROOT.glob('*/SKILL.md')}
        self.assertEqual(actual, set(PACKAGES))
        for root, artifact in artifacts(ROOT):
            if artifact.kind == 'standalone':
                self.assertEqual(artifact.skills[0].name, PACKAGES[root.name])

    def test_complete_supporting_resources_and_safe_relative_links(self):
        for root, artifact in artifacts(ROOT):
            for name, (_, raw) in artifact.files.items():
                if not name.endswith('.md'):
                    continue
                file = root/name
                for target in re.findall(r'\]\(([^\s)]+)\)', raw.decode('utf-8')):
                    url = urlsplit(target)
                    if url.scheme or url.netloc or not url.path:
                        continue
                    resolved = (file.parent/unquote(url.path)).resolve()
                    self.assertIn(ROOT, resolved.parents)
                    self.assertTrue(resolved.exists(), str(file.relative_to(ROOT)))

    def test_no_private_directories_or_license_files(self):
        for name in ['development', 'publication', 'public-docs']:
            self.assertFalse((ROOT/name).exists())
        for file in ROOT.rglob('*'):
            if '.git' not in file.relative_to(ROOT).parts:
                self.assertFalse(re.match(r'licen[cs]e(?:[._-]|$)', file.name, re.I))


if __name__ == '__main__':
    unittest.main()
