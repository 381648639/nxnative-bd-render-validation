#!/usr/bin/env python3
"""Drive real guest gameplay through DM_CTL and publish small private captures.

The control release accepts an ordered commands.json array of batches. Each batch
has a unique increasing id and steps containing key/hold/wait, shot, burst, passdump,
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
from collect_visual_sources import collect

parser = argparse.ArgumentParser()
parser.add_argument('runtime', type=Path)
parser.add_argument('evidence', type=Path)
parser.add_argument('--minutes', type=int, default=75)
parser.add_argument('--diagnostics', action='store_true', help='Enable shader and pixel tracing')
parser.add_argument('--autoplay-roark', action='store_true', help='Drive the supplied leader save with final-frame OCR')
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
(evidence / 'uniforms').mkdir(exist_ok=True)
env = dict(os.environ, **manifest['env'])
for key in ('DM_ROOT', 'DM_ROMFS', 'DM_SAVE', 'DM_TEMP', 'DM_FONT_DIR', 'DM_MSL_DIR', 'DM_NVN_SHMAP'):
    env[key] = str(root / env[key])
env.update(DM_CTL=str(ctl), DM_WINDOW='1', DM_AUDIO='0', DM_KBD='Lucas',
           DM_TEST_NO_BC='1', DM_NO_BC_ASTC='all', DM_PRESENT_LINK='0',
           DM_BOOTPROF='1', DM_LONGFRAME='0', DM_LANG='en')
for key in ('DM_NVN_PASSDUMP_ALL', 'DM_NVN_SNAPRAW', 'DM_NVN_PIXEL_HISTORY',
            'DM_NVN_TRACE_SHADERS', 'DM_NVN_CBDUMP_KEY', 'DM_NVN_CBDUMP'):
    env.pop(key, None)
if args.diagnostics:
    env.update(DM_NVN_PASSDUMP_ALL='1', DM_NVN_SNAPRAW='1',
               DM_NVN_PIXEL_HISTORY='0.5,0.625;0.5,0.373611;0.390625,0.555556',
               DM_NVN_TRACE_SHADERS='b8b1925cc16f8247_b,bf70b833d622277c_b',
               DM_NVN_CBDUMP_KEY='b8b1925cc16f8247_b',
               DM_NVN_CBDUMP=str(evidence / 'uniforms'))
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
launches = []
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
    launches.append({'elapsed': round(time.monotonic() - began, 3),
                     'pid': process.pid,
                     'env': {k: v for k, v in actual.items() if k.startswith('DM_')}})
    (evidence / 'launches.json').write_text(json.dumps(launches, indent=2) + '\n')
    upload(evidence / 'launches.json')
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

def capture_burst(step):
    name = step['burst']
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', name):
        raise ValueError('Invalid burst name')
    key = step.get('key', '')
    if key and not re.fullmatch(r'[A-Za-z0-9+./-]{1,100}', key):
        raise ValueError('Invalid burst key')
    count, stride, lead = (int(step.get(k, d)) for k, d in
                           [('count', 24), ('stride', 1), ('lead', 2)])
    if not (1 <= count <= 48 and 1 <= stride <= 60 and 1 <= lead <= 600):
        raise ValueError('Invalid burst frame schedule')
    hold = float(step.get('hold', 4))
    if not 0 <= hold <= 30:
        raise ValueError('Burst hold must be between 0 and 30 seconds')
    folder = evidence / 'bursts' / name
    folder.mkdir(parents=True, exist_ok=False)
    prefix = folder / 'frame'
    # Queue all captures before pressing the key: DM_CTL key holds block its
    # input thread. Network uploads begin after the entire burst completes.
    began_burst = time.monotonic()
    command(f'shotburst {count} {stride} {lead} {prefix}')
    if key:
        command(key + '~' + str(hold))
    until = began_burst + 120
    paths = [folder / f'frame-{i:03d}.png' for i in range(count)]
    previous = None
    while time.monotonic() < until and process.poll() is None:
        sizes = [p.stat().st_size if p.exists() else 0 for p in paths]
        if all(s > 100 for s in sizes) and sizes == previous and time.monotonic() - began_burst >= hold:
            break
        previous = sizes
        time.sleep(0.3)
    meta = {'step': step, 'elapsed': round(time.monotonic() - began, 3),
            'duration': round(time.monotonic() - began_burst, 3),
            'completed': [p.name for p in paths if p.exists() and p.stat().st_size > 100],
            'limitation': 'PNG readbacks wait for the GPU and affect frame timing; this is not a performance test.'}
    (folder / 'capture.json').write_text(json.dumps(meta, indent=2) + '\n')
    archive = Path(shutil.make_archive(str(folder), 'zip', folder))
    upload(archive)
    complete = [p for p in paths if p.exists() and p.stat().st_size > 100]
    if complete:
        shutil.copyfile(complete[-1], evidence / 'latest.png')
        upload(evidence / 'latest.png')
    print('Captured burst', name, len(complete), 'of', count, flush=True)

try:
    start_process()
    upload(evidence / 'conditions.json')
    pause(25)
    capture('boot-025')
    publish_status()
    if args.autoplay_roark:
        from play_roark import play
        play(root, evidence, process, command, pause, upload, publish_status)
        upload(log)
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
                        if 'burst' in step:
                            capture_burst(step)
                        elif 'key' in step:
                            if not re.fullmatch(r'[A-Za-z0-9+./-]{1,100}', step['key']):
                                raise ValueError('Invalid key specification')
                            command(step['key'] + '~' + str(float(step.get('hold', 0.2))))
                            pause(float(step.get('hold', 0.2)) + float(step.get('wait', 2)))
                        elif 'shot' in step:
                            capture(step['shot'])
                        elif 'wait' in step and len(step) == 1:
                            pause(step['wait'])
                        elif 'passdump' in step:
                            command('passdump ' + str(min(5, int(step['passdump']))))
                        elif step.get('log'):
                            upload(log)
                        elif 'sample' in step:
                            name = step['sample']
                            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', name):
                                raise ValueError('Invalid sample name')
                            path = evidence / (name + '-sample.txt')
                            subprocess.run(['/usr/bin/sample', str(process.pid), '5', '10', '-file', str(path)],
                                           capture_output=True, timeout=30, check=False)
                            if path.exists():
                                upload(path)
                        elif 'background' in step:
                            command('background ' + ('1' if step['background'] else '0'))
                            pause(step.get('wait', 5))
                        elif step.get('save'):
                            archive = Path(shutil.make_archive(str(evidence / 'live-save'), 'zip', root / 'run/save'))
                            upload(archive)
                        elif step.get('diagnostics'):
                            collect(root, evidence)
                            archive = Path(shutil.make_archive(str(evidence.parent / 'live-diagnostics'), 'zip', evidence))
                            upload(archive)
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
                        elif 'verdict' in step:
                            verdict = step['verdict']
                            names = step.get('screenshots', [])
                            if verdict not in ('pass', 'fail') or not names:
                                raise ValueError('A visual verdict needs pass/fail and inspected screenshots')
                            if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', n) or not (shots / (n + '.png')).is_file() for n in names):
                                raise ValueError('Every inspected screenshot must exist in this session')
                            record = {'verdict': verdict, 'screenshots': names,
                                      'source_commit': os.environ['GITHUB_SHA'],
                                      'run_id': os.environ['GITHUB_RUN_ID'],
                                      'platform': 'macOS Metal; iPhone is untested'}
                            (evidence / 'verdict.json').write_text(json.dumps(record, indent=2) + '\n')
                            upload(evidence / 'verdict.json')
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
    collect(root, evidence)
    # The actual game saves allow subsequent scene comparisons without replaying
    # the entire introduction. They are uploaded only to this private repository.
    shutil.copytree(root / 'run/save', evidence / 'save', dirs_exist_ok=True)
    shutil.make_archive(str(evidence / 'game-save'), 'zip', root / 'run/save')
    upload(evidence / 'game-save.zip')
    upload(log)
    print('Runtime session ended. Screenshots still need visual inspection.', flush=True)
