#!/usr/bin/env python3
"""Drive real guest gameplay through DM_CTL and publish small private captures.

The control release accepts an ordered commands.json array of batches. Each batch
has a unique increasing id and steps containing key/hold/wait, shot, passdump,
texdump, restart (optional env), or stop. No shell commands are accepted.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('runtime', type=Path)
parser.add_argument('evidence', type=Path)
parser.add_argument('--minutes', type=int, default=75)
args = parser.parse_args()
root, evidence = args.runtime.resolve(), args.evidence.resolve()
evidence.mkdir(parents=True, exist_ok=True)
shots = evidence / 'shots'
shots.mkdir(exist_ok=True)
manifest = json.loads((root / 'runtime.json').read_text())
repo = os.environ.get('BD_ASSET_REPOSITORY', os.environ['GITHUB_REPOSITORY'])
tag = 'bd-visual-' + os.environ['GITHUB_RUN_ID']
ctl = root / 'run/ctl.txt'
log = evidence / 'game.log'
for directory in ('run/save', 'run/temp'):
    (root / directory).mkdir(parents=True, exist_ok=True)
env = dict(os.environ, **manifest['env'])
for key in ('DM_ROOT', 'DM_ROMFS', 'DM_SAVE', 'DM_TEMP', 'DM_FONT_DIR', 'DM_MSL_DIR', 'DM_NVN_SHMAP'):
    env[key] = str(root / env[key])
env.update(DM_CTL=str(ctl), DM_WINDOW='1', DM_AUDIO='0', DM_KBD='Lucas',
           DM_TEST_NO_BC='1', DM_NO_BC_ASTC='all', DM_PRESENT_LINK='0',
           DM_BOOTPROF='1', DM_LONGFRAME='0', DM_LANG='en')
record = dict(manifest, env={k: v for k, v in env.items() if k.startswith('DM_')},
              run_id=os.environ['GITHUB_RUN_ID'], release=tag,
              visual_verdict='pending human inspection')
(evidence / 'conditions.json').write_text(json.dumps(record, indent=2) + '\n')

def gh(*argv, check=True):
    return subprocess.run(['gh', *argv, '--repo', repo], capture_output=True,
                          text=True, timeout=60, check=check)

gh('release', 'create', tag, '--title', 'Private live gameplay validation ' + os.environ['GITHUB_RUN_ID'],
   '--notes', 'Real guest gameplay captures from legacy Metal replay. No device pass is claimed.',
   '--prerelease')
process = None
stream = None
last_id = 0
events = []
began = time.monotonic()
running = True

def stop_process():
    global process, stream
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if stream:
        stream.close()

def start_process(extra=None):
    global process, stream
    stop_process()
    ctl.write_text('')
    actual = dict(env)
    for k, v in (extra or {}).items():
        if not re.fullmatch(r'DM_[A-Z0-9_]+', k):
            raise ValueError('Only DM environment overrides are accepted')
        actual[k] = str(v)
    stream = log.open('ab', buffering=0)
    stream.write(b'\n=== Real guest process start ===\n')
    process = subprocess.Popen([str(root / manifest['host']), str(root / manifest['patched'])],
                               cwd=root / 'run', env=actual, stdout=stream,
                               stderr=subprocess.STDOUT)
    print('Started real guest game, pid', process.pid, flush=True)

def command(text):
    with ctl.open('a') as f:
        f.write(text + '\n')

def pause(seconds):
    until = time.monotonic() + min(float(seconds), 180)
    while time.monotonic() < until and process.poll() is None:
        time.sleep(0.1)

def upload(path):
    result = gh('release', 'upload', tag, str(path), '--clobber', check=False)
    if result.returncode:
        print('Capture upload failed:', result.stderr[-250:], flush=True)

def capture(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', name):
        raise ValueError('Invalid capture name')
    path = shots / (name + '.png')
    if path.exists():
        path.unlink()
    command('shot ' + str(path))
    until = time.monotonic() + 35
    previous = -1
    while time.monotonic() < until and process.poll() is None:
        size = path.stat().st_size if path.exists() else 0
        if size > 100 and size == previous:
            upload(path)
            shutil.copyfile(path, evidence / 'latest.png')
            upload(evidence / 'latest.png')
            print('Captured', name, size, 'bytes', flush=True)
            return
        previous = size
        time.sleep(0.3)
    print('No completed game frame for capture', name, flush=True)

def publish_status():
    tail = log.read_bytes()[-24000:].decode(errors='replace') if log.exists() else ''
    (evidence / 'status.json').write_text(json.dumps({
        'last_id': last_id, 'elapsed': round(time.monotonic() - began),
        'pid': process.pid, 'returncode': process.poll(), 'log_tail': tail,
        'shots': [p.name for p in shots.glob('*.png')]
    }, indent=2) + '\n')
    upload(evidence / 'status.json')
    (evidence / 'events.json').write_text(json.dumps(events, indent=2) + '\n')
    upload(evidence / 'events.json')

try:
    start_process()
    upload(evidence / 'conditions.json')
    pause(25)
    capture('boot-025')
    publish_status()
    last_status = time.monotonic()
    while running and time.monotonic() - began < args.minutes * 60:
        if process.poll() is not None:
            publish_status()
            print('Guest process exited with', process.returncode, flush=True)
            break
        remote = evidence / 'commands.json'
        result = gh('release', 'download', tag, '--pattern', 'commands.json', '--output', str(remote), '--clobber', check=False)
        if result.returncode == 0:
            try:
                batches = json.loads(remote.read_text())
                for batch in sorted(batches, key=lambda b: b['id']):
                    if int(batch['id']) <= last_id:
                        continue
                    for step in batch['steps']:
                        events.append({'batch': batch['id'], 'elapsed': round(time.monotonic() - began, 2), 'step': step})
                        if 'key' in step:
                            if not re.fullmatch(r'[A-Za-z0-9+./-]{1,100}', step['key']):
                                raise ValueError('Invalid key specification')
                            command(step['key'] + '~' + str(float(step.get('hold', 0.2))))
                            pause(float(step.get('hold', 0.2)) + float(step.get('wait', 2)))
                        elif 'shot' in step:
                            capture(step['shot'])
                        elif 'wait' in step and 'restart' not in step:
                            pause(step['wait'])
                        elif 'passdump' in step:
                            command('passdump ' + str(min(5, int(step['passdump']))))
                        elif 'texdump' in step:
                            name = step['texdump']
                            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name):
                                raise ValueError('Invalid texture capture name')
                            command('texdump ' + str(shots / (name + '-%d.png')))
                            pause(5)
                            for texture in shots.glob(name + '-*.png'):
                                upload(texture)
                        elif 'restart' in step:
                            start_process(step.get('env'))
                            pause(step.get('wait', 25))
                        elif step.get('stop'):
                            running = False
                    last_id = int(batch['id'])
                    publish_status()
            except (ValueError, KeyError, TypeError) as e:
                print('Control data rejected:', e, flush=True)
        if time.monotonic() - last_status > 90:
            publish_status()
            last_status = time.monotonic()
        time.sleep(12)
finally:
    stop_process()
    publish_status()
    # The actual game saves allow subsequent scene comparisons without replaying
    # the entire introduction. They are uploaded only to this private repository.
    shutil.copytree(root / 'run/save', evidence / 'save', dirs_exist_ok=True)
    shutil.make_archive(str(evidence / 'game-save'), 'zip', root / 'run/save')
    upload(evidence / 'game-save.zip')
    upload(log)
    print('Runtime session ended. Screenshots still need visual inspection.', flush=True)
