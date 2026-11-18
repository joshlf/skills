#!/usr/bin/env python3
"""Probe real host discovery with public-only files, without any model turn."""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import platform
import sys
import time

def response(process, pending, matches, timeout=60):
    # Use unbuffered byte reads: a TextIOWrapper can hold a second complete
    # message while select reports that the underlying fd has no new bytes.
    # Keep partial notifications across calls so they cannot corrupt the next
    # request's response framing.
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            while b"\n" in pending:
                end = pending.index(b"\n")
                raw = bytes(pending[:end])
                del pending[:end+1]
                if not raw.strip(): continue
                value = json.loads(raw)
                if matches(value): return value
            if not selector.select(timeout=min(1, max(0, deadline-time.monotonic()))): continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk: raise RuntimeError('Host exited before discovery response')
            pending.extend(chunk)
            if len(pending) > 16*1024*1024: raise RuntimeError('Oversized host protocol message')
        raise TimeoutError('Host discovery timed out')
    finally:
        selector.close()


def send(process, value):
    process.stdin.write((json.dumps(value)+'\n').encode())
    process.stdin.flush()


def stop(process):
    process.terminate()
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    for stream in [process.stdin,process.stdout]:
        if stream:stream.close()


def load_tooling(path, snapshot):
    """Load explicitly supplied reviewed tooling, never the tested copy."""
    path = path.resolve(strict=True)
    if path == snapshot or snapshot in path.parents:
        raise ValueError('Reviewed tooling must be outside the tested snapshot')
    spec = importlib.util.spec_from_file_location('host_probe_packages', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def packet(snapshot, expected_inventory, tooling, selected_names=None):
    """Bind the complete source inventory before selecting complete leaves."""
    bound = json.loads(expected_inventory.read_text())
    fields = ('path', 'mode', 'bytes', 'sha256')
    expected = [{key: row[key] for key in fields} for row in bound['inventory']]
    files = tooling.capture_directory(snapshot)
    if (tooling.inventory(files) != expected
            or tooling.content_sha256(files) != bound['content_sha256']):
        raise RuntimeError('Transferred snapshot differs from the checked candidate')

    # Locate complete source offerings before selecting leaves. The reviewed
    # interpreter validates every native child; nested SKILL.md examples remain
    # resources rather than becoming a second discovery rule here.
    roots = tooling.offering_roots(row['path'] for row in expected)
    leaves, offered, aliases = {}, [], {}
    selected_names = None if selected_names is None else tuple(selected_names)
    if selected_names is not None and (not selected_names
            or len(set(selected_names)) != len(selected_names)):
        raise ValueError('Select skills without duplicates')
    matched = set()
    artifacts = []
    for root in sorted(roots):
        prefix = root + '/'
        captured = {name[len(prefix):]: value for name, value in files.items()
                    if name.startswith(prefix)}
        artifact = tooling.describe(captured, root.split('/')[-1])
        if (artifact.kind == 'native') != root.startswith('systems/'):
            raise RuntimeError('Artifact shape disagrees with its source root')
        artifacts.append(artifact)
        chosen = []
        for skill in artifact.skills:
            entrypoint = prefix + (skill.directory + '/' if skill.directory else '') + 'SKILL.md'
            identities = ({artifact.package_name+':'+skill.name} if artifact.kind == 'native'
                          else set(skill.aliases))
            selections = identities.intersection(selected_names or ())
            if selected_names is not None and not selections:
                continue
            matched.update(selections)
            chosen.append(skill.name)
            folder = skill.directory.split('/')[-1] if skill.directory else root
            for alias in skill.aliases:
                prior = aliases.setdefault(alias.casefold(), entrypoint)
                if prior != entrypoint:
                    raise RuntimeError('Selected flat invocation collision: ' + alias)
            offered.append({'name': skill.name, 'folder': folder,
                            'source': entrypoint, 'kind': artifact.kind,
                            'package': artifact.package_name})
        if not chosen:
            continue
        planned = tooling.plan_skills(artifact, chosen)
        for destination, value in planned.files.items():
            if destination in leaves:
                raise RuntimeError('Selected flat destination collision: ' + destination)
            leaves[destination] = value
    tooling.validate_namespace(artifacts)
    if selected_names is not None and matched != set(selected_names):
        raise ValueError('Unknown selected skill: ' + str(sorted(set(selected_names)-matched)))
    return tooling.validate_files(leaves), offered, bound['content_sha256']


def materialize(files, destination, tooling):
    plan = tooling.Plan(files, {name: name for name in files}, 'skills', None, ())
    return tooling.write_new(plan, destination)


def check_selected(rows, offered, destination):
    """Require one selected path per name, including shadowing outside the stage."""
    selected = []
    for skill in offered:
        matches = [row for row in rows if row['name'] == skill['name']]
        expected = destination / skill['folder'] / 'SKILL.md'
        if len(matches) != 1 or Path(matches[0]['path']).resolve() != expected.resolve():
            raise RuntimeError('Missing, duplicate or shadowed host selection: ' + skill['name'])
        selected.append(matches[0])
    unexpected = [row for row in rows if destination in Path(row['path']).parents
                  and row['name'] not in {skill['name'] for skill in offered}]
    if unexpected:
        raise RuntimeError('Unexpected candidate skills selected by host')
    return selected


def codex(root, output, offered, destination):
    (root/'codex-state').mkdir()
    (root/'codex-logs').mkdir()
    with (output/'codex.stderr').open('w') as error:
        command = ['codex', 'app-server', '--stdio',
            '-c', 'sqlite_home='+json.dumps(str(root/'codex-state')),
            '-c', 'log_dir='+json.dumps(str(root/'codex-logs')),
            '-c', 'history.persistence="none"', '-c', 'analytics.enabled=false']
        (output/'codex.argv.json').write_text(json.dumps(command, indent=2)+'\n')
        process = subprocess.Popen(command, cwd=root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error)
        pending = bytearray()
        try:
            send(process, {'id': 1, 'method': 'initialize', 'params': {
                'clientInfo': {'name': 'publication-discovery', 'version': '2'},
                'capabilities': {'experimentalApi': True}}})
            initialized = response(process, pending, lambda v: v.get('id') == 1)
            if 'error' in initialized:
                raise RuntimeError('Codex initialize failed: ' + str(initialized['error']))
            send(process, {'method': 'initialized', 'params': {}})
            send(process, {'id': 2, 'method': 'skills/list', 'params': {
                'cwds': [str(root)], 'forceReload': True}})
            value = response(process, pending, lambda v: v.get('id') == 2)
            (output/'codex.protocol.json').write_text(json.dumps(value, indent=2)+'\n')
            if 'error' in value:
                raise RuntimeError('Codex discovery failed: ' + str(value['error']))
            data = value['result']['data']
            if any(row.get('errors') for row in data):
                raise RuntimeError('Codex reported skill loading errors')
            rows = [{'name': skill['name'], 'path': skill['path']}
                    for row in data for skill in row['skills']]
            return {'protocol': 'skills/list', 'status': 'passed',
                    'selected': check_selected(rows, offered, destination)}
        finally:
            stop(process)


def claude(root, output, offered, destination):
    config = root/'claude-config'
    config.mkdir()
    with (output/'claude.stderr').open('w') as error:
        process = subprocess.Popen(['claude', '-p', '--verbose', '--input-format', 'stream-json',
            '--output-format', 'stream-json', '--setting-sources', 'project',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
            '--settings', '{"disableAllHooks":true,"syncClaudeAiSkills":false}'],
            cwd=root, env={**os.environ, 'CLAUDE_CONFIG_DIR': str(config)},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error)
        pending = bytearray()
        try:
            send(process, {'type': 'control_request', 'request_id': 'discovery',
                           'request': {'subtype': 'initialize', 'hooks': None}})
            value = response(process, pending, lambda v: v.get('type') == 'control_response'
                             and v.get('response', {}).get('request_id') == 'discovery')
            (output/'claude.protocol.json').write_text(json.dumps(value, indent=2)+'\n')
            envelope = value['response']
            if envelope.get('subtype') != 'success':
                raise RuntimeError('Claude initialize failed: ' + str(envelope))
            commands = envelope['response'].get('commands', [])
            names = [command['name'] for command in commands]
            if any(names.count(skill['name']) != 1 for skill in offered):
                raise RuntimeError('Claude candidate set differs or has duplicate commands')
            # SDK initialize exposes command metadata, but no resolved skill path.
            # Filesystem verification is separate evidence, not path selection.
            return {'protocol': 'SDK initialize commands', 'status': 'passed',
                    'names': sorted(skill['name'] for skill in offered),
                    'selected_paths': 'not exposed by this interface'}
        finally:
            stop(process)


def gemini(root, output, offered, destination):
    home = root/'gemini-home'
    (home/'.gemini').mkdir(parents=True)
    (home/'.gemini/settings.json').write_text(json.dumps(
        {'security': {'folderTrust': {'enabled': False}}, 'telemetry': {'enabled': False}}))
    with (output/'gemini.stderr').open('w') as error:
        value = subprocess.run(['gemini', 'skills', 'list'], cwd=root,
            env={**os.environ, 'GEMINI_CLI_HOME': str(home), 'NO_COLOR': '1'},
            stdout=subprocess.PIPE, stderr=error, text=True, timeout=60, check=True)
    (output/'gemini.stdout').write_text(value.stdout)
    rows = []
    for block in value.stdout.split('\n\n'):
        name = re.search(r'^([a-z0-9-]+) \[Enabled\]', block, re.M)
        path = re.search(r'^\s*Location:\s*(.+?)\s*$', block, re.M)
        if name and path:
            rows.append({'name': name[1], 'path': path[1]})
    return {'protocol': 'skills list', 'status': 'passed',
            'selected': check_selected(rows, offered, destination)}


HOSTS = {'codex': ('.agents/skills', codex), 'claude': ('.claude/skills', claude),
         'gemini': ('.agents/skills', gemini)}


def probe(snapshot, output, expected_inventory, tooling_path, hosts=None, selected_names=None):
    snapshot, output = snapshot.resolve(strict=True), output.resolve()
    if output == snapshot or snapshot in output.parents:
        raise ValueError('Keep discovery results outside the tested snapshot')
    tooling = load_tooling(tooling_path, snapshot)
    files, offered, content_digest = packet(snapshot, expected_inventory, tooling, selected_names)
    hosts = tuple(HOSTS if hosts is None else hosts)
    if not hosts or len(set(hosts)) != len(hosts) or set(hosts)-set(HOSTS):
        raise ValueError('Select supported hosts without duplicates')
    output.mkdir(parents=True, exist_ok=False)
    result = {'kind': 'complete-leaf discovery; no model turns or effectiveness measurement',
              'hosts': {}, 'private_source_checkout': 'not supplied',
              'content_sha256': content_digest, 'offerings': offered,
              'tooling_sha256': hashlib.sha256(tooling_path.read_bytes()).hexdigest(),
              'os': platform.system(), 'kernel': platform.release(),
              'os_release': platform.mac_ver()[0] if platform.system() == 'Darwin' else platform.release(),
              'architecture': platform.machine()}
    for host in hosts:
        location, discover = HOSTS[host]
        cell = {'behavior': 'not tested; no model turn', 'body_loading': 'not tested by host'}
        result['hosts'][host] = cell
        try:
            executable = shutil.which(host)
            if executable is None:
                raise FileNotFoundError('Host executable unavailable: '+host)
            cell['executable'] = str(Path(executable).resolve(strict=True))
            version = subprocess.run([host, '--version'], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, timeout=30, check=True)
            cell['version'] = version.stdout.strip()
            with tempfile.TemporaryDirectory(prefix='complete-leaf-'+host+'-') as directory:
                root = Path(directory).resolve()
                destination = root/location
                destination.parent.mkdir(parents=True)
                cell['filesystem_resources'] = materialize(files, destination, tooling)
                try:
                    cell['discovery'] = discover(root, output, offered, destination)
                finally:
                    cell['owned_state'] = [
                        {'path': path.relative_to(root).as_posix(),
                         'bytes': path.stat().st_size}
                        for prefix in ('codex-state', 'codex-logs')
                        for path in sorted((root/prefix).rglob('*')) if path.is_file()]
        # Protocol/schema failures are failed cells too. Retaining them allows
        # the remaining independent hosts to run without manufacturing a pass.
        except Exception as error:
            cell['discovery'] = {'status': 'failed', 'error': str(error),
                                 'error_type': type(error).__name__}
        (output/'discovery.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-inventory', type=Path, required=True)
    parser.add_argument('--tooling', type=Path, required=True,
                        help='Reviewed skill_packages.py outside the tested snapshot')
    parser.add_argument('--host', choices=tuple(HOSTS), action='append', dest='hosts')
    parser.add_argument('--skill', action='append', dest='selected_names',
                        help='Standalone alias or package-qualified native name; default all')
    args = parser.parse_args()
    result = probe(args.snapshot, args.output, args.expected_inventory, args.tooling,
                   args.hosts, args.selected_names)
    print(json.dumps(result, indent=2))
    raise SystemExit(any(cell['discovery']['status'] != 'passed'
                         for cell in result['hosts'].values()))
