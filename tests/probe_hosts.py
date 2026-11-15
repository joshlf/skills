#!/usr/bin/env python3
"""Probe real host discovery with public-only files, without any model turn."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time

EXPECTED = {'clear-writing', 'commit-message', 'model-refinement', 'robust-code',
            'skill-authorship', 'reader-oriented-explanation', 'authorship-disclosure'}


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


def probe(snapshot, output, expected_inventory=None):
    snapshot,output=snapshot.resolve(),output.resolve()
    if output==snapshot or snapshot in output.parents:
        raise ValueError('Keep discovery results outside the tested snapshot')
    rows=[]
    for path in sorted(snapshot.rglob('*')):
        if '.git' in path.relative_to(snapshot).parts: continue
        if path.is_symlink(): raise RuntimeError('Linked candidate input')
        if path.is_file():
            raw=path.read_bytes()
            rows.append({'path':path.relative_to(snapshot).as_posix(),
                         'mode':'100755' if path.stat().st_mode & 0o111 else '100644',
                         'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    encoded=(json.dumps(rows,sort_keys=True,indent=2,ensure_ascii=False)+'\n').encode()
    content_digest=hashlib.sha256(encoded).hexdigest()
    if expected_inventory:
        bound=json.loads(expected_inventory.read_text())
        if rows!=bound['inventory'] or content_digest!=bound['content_sha256']:
            raise RuntimeError('Transferred snapshot differs from the checked candidate')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='public-only-host-probe-') as directory:
        root = Path(directory).resolve()
        for package in snapshot.iterdir():
            if package.is_dir() and (package/'SKILL.md').is_file():
                for location in ['.agents/skills', '.claude/skills']:
                    shutil.copytree(package, root/location/package.name)
        for directory in ['claude-config', 'gemini-home/.gemini']:
            (root/directory).mkdir(parents=True)
        (root/'gemini-home/.gemini/settings.json').write_text(json.dumps(
            {'security':{'folderTrust':{'enabled':False}},'telemetry':{'enabled':False}}))
        result = {'kind':'native discovery; no model turns or effectiveness measurement',
                  'hosts':{}, 'private_source_checkout':'not supplied', 'content_sha256':content_digest}
        with (output/'codex.stderr').open('w') as error:
            process = subprocess.Popen(['codex','app-server','--stdio'],cwd=root,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error)
            pending=bytearray()
            try:
                send(process,{'id':1,'method':'initialize','params':{
                    'clientInfo':{'name':'publication-discovery','version':'1'},
                    'capabilities':{'experimentalApi':True}}})
                initialized=response(process,pending,lambda v:v.get('id')==1)
                if 'error' in initialized: raise RuntimeError('Codex initialize failed')
                send(process,{'method':'initialized','params':{}})
                send(process,{'id':2,'method':'skills/list','params':{'cwds':[str(root)],'forceReload':True}})
                value=response(process,pending,lambda v:v.get('id')==2)
                if 'error' in value: raise RuntimeError('Codex discovery failed')
                names={s['name'] for row in value['result']['data'] for s in row['skills']
                       if str(root) in s['path']}
                if names != EXPECTED: raise RuntimeError('Codex candidate set differs')
                result['hosts']['codex']={'names':sorted(names),'protocol':'skills/list'}
            finally: stop(process)
        with (output/'claude.stderr').open('w') as error:
            process=subprocess.Popen(['claude','-p','--verbose','--input-format','stream-json',
                '--output-format','stream-json','--setting-sources','project',
                '--strict-mcp-config','--mcp-config','{"mcpServers":{}}',
                '--settings','{"disableAllHooks":true,"syncClaudeAiSkills":false}'],
                cwd=root,env={**os.environ,'CLAUDE_CONFIG_DIR':str(root/'claude-config')},
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error)
            pending=bytearray()
            try:
                send(process,{'type':'control_request','request_id':'discovery',
                              'request':{'subtype':'initialize','hooks':None}})
                value=response(process,pending,lambda v:v.get('type')=='control_response' and
                               v.get('response',{}).get('request_id')=='discovery')
                envelope=value['response']
                if envelope.get('subtype')!='success': raise RuntimeError('Claude initialize failed')
                names={c['name'] for c in envelope['response'].get('commands',[])} & EXPECTED
                if names != EXPECTED: raise RuntimeError('Claude candidate set differs')
                result['hosts']['claude']={'names':sorted(names),'protocol':'SDK initialize commands'}
            finally: stop(process)
        with (output/'gemini.stderr').open('w') as error:
            value=subprocess.run(['gemini','skills','list'],cwd=root,
                env={**os.environ,'GEMINI_CLI_HOME':str(root/'gemini-home'),'NO_COLOR':'1'},
                stdout=subprocess.PIPE,stderr=error,text=True,timeout=60,check=True)
            names=set()
            for block in value.stdout.split('\n\n'):
                if str(root) in block and 'Location:' in block:
                    match=re.search(r'^([a-z0-9-]+) \[Enabled\]',block,re.M)
                    if match:names.add(match[1])
            if names != EXPECTED:raise RuntimeError('Gemini candidate set differs')
            result['hosts']['gemini']={'names':sorted(names),'protocol':'skills list'}
        for executable in result['hosts']:
            version=subprocess.run([executable,'--version'],stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,text=True,check=True)
            result['hosts'][executable]['version']=version.stdout.strip()
        (output/'discovery.json').write_text(json.dumps(result,indent=2)+'\n')
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expected-inventory',type=Path)
    args=parser.parse_args()
    print(json.dumps(probe(args.snapshot,args.output,args.expected_inventory),indent=2))
