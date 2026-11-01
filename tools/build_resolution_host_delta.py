"""Rebuild the iOS host from verified private r5 inputs after a Mac visual pass.

ROM and shader ZIP entries are reused without recompression when assembling the
IPA locally. This build does not change guest code or the shader toolchain.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('config', type=Path)
parser.add_argument('inputs', type=Path)
parser.add_argument('validation', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
source, config, inputs, output = (p.resolve() for p in (args.source, args.config, args.inputs, args.output))
output.mkdir(parents=True, exist_ok=True)
manifest = json.loads((inputs / 'verified-r5-host-inputs.json').read_text())
assert manifest['base_ipa_sha256'] == 'd3672939662b86210b2f10f2c0532e51d1326521227212c41c77e03d9a33cfd6'
archive = inputs / 'verified-r5-host-inputs.zip'
assert archive.stat().st_size == manifest['archive_size']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
proof = json.loads(args.validation.read_text())
production_source = source / 'dm/host/hle_unity_screen.c'
production_hash = hashlib.sha256(production_source.read_bytes()).hexdigest()
assert proof['verdict'] == 'pass' and proof['production_source_sha256'] == production_hash
assert proof['patch_sha256'] == hashlib.sha256((config / 'patches/unity-resolution.patch').read_bytes()).hexdigest()
assert proof['presets_passed'] == ['native', '1280x720', '960x540', '640x360']
assert proof['final_presentation_capture'] is True
assert proof['phone_power_verified'] is False

with zipfile.ZipFile(archive) as z:
    assert set(z.namelist()) == {'base-app/' + p for p in manifest['files']}
    for name, expected in manifest['files'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        data = z.read('base-app/' + name)
        assert len(data) == expected['size'] and hashlib.sha256(data).hexdigest() == expected['sha256']
        path = output / 'base-app' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
base_app = output / 'base-app'

def sections(raw):
    assert struct.unpack_from('<I', raw)[0] == 0xfeedfacf
    position = 32
    out = {}
    for _ in range(struct.unpack_from('<I', raw, 16)[0]):
        command, size = struct.unpack_from('<II', raw, position)
        assert size >= 8 and position + size <= len(raw)
        if command == 0x19:
            segment = raw[position + 8:position + 24].split(b'\0')[0].decode()
            for i in range(struct.unpack_from('<I', raw, position + 64)[0]):
                at = position + 72 + 80 * i
                name = raw[at:at + 16].split(b'\0')[0].decode()
                length, offset = struct.unpack_from('<QI', raw, at + 40)
                out[segment, name] = (offset, length)
        position += size
    return out

raw = (base_app / 'DmIOS').read_bytes()
layout = sections(raw)
patched = output / 'patched'
patched.mkdir(exist_ok=True)
module_hashes = {}
for name in ('main', 'subsdk0', 'sdk'):
    for suffix in ('fixups', 'gates', 'cuts', 'obs'):
        shutil.copyfile(base_app / 'dm' / (name + '.' + suffix + '.tsv'), patched / (name + '.' + suffix + '.tsv'))
    header = dict(line[2:].split('\t', 1) for line in (patched / (name + '.fixups.tsv')).read_text().splitlines() if line.startswith('# '))
    split = (int(header['TEXT_END'], 16) + 0x3fff) & ~0x3fff
    patch_at = int(header['PATCH_OFF'], 16)
    assert patch_at > split
    offset, length = layout['__TEXT', '__dm' + name + 'img']
    image = bytearray(raw[offset:offset + length])
    writable, writable_length = layout['__DM' + name + 'W', '__img']
    assert writable_length == patch_at - split
    assert not any(image[split:patch_at])
    image[split:patch_at] = raw[writable:writable + writable_length]
    assert len(image) == length
    module_hashes[name] = hashlib.sha256(image).hexdigest()
    (patched / (name + '.patched.bin')).write_bytes(image)
    if name == 'main':
        assert header['BUILD_ID'] == '94ceae325c205c4b9d6f7235552f28fd'
        path = patched / 'main.fixups.tsv'
        with path.open('a') as f:
            f.write('# UNITY_SCREEN_RESOLUTION\t1\n')
del raw

ios = source / 'dm/ios'
gen = ios / 'Gen'
assert not gen.exists(), 'Use a clean source checkout for the host build'
gen.mkdir()
env = dict(os.environ, GAME='0100000011D90000', GFXAPI='nvn', DM_IOS_RENDERER='legacy',
           DM_IOS_DEPLOYMENT_TARGET='16.1', DM_SCHEME_NAME='DmIOS',
           DM_BUNDLE_ID='org.nxnative.0100000011d90000', DM_DISPLAY_NAME='Pokémon Brilliant Diamond',
           DM_APP_VERSION='1.3.0', DM_TEAM_ID='0000000000', DM_SHOW_FPS='YES',
           DM_LANG='en-US', DM_APP_CATEGORY='public.app-category.role-playing-games', DM_APPICON='')

def run(argv, cwd=None):
    subprocess.run([str(a) for a in argv], cwd=cwd, env=env, check=True)

build_config = subprocess.check_output(['python3', 'tools/gen_build.py', str(source / 'dm/host'), str(gen)], cwd=ios, env=env).decode()
flags = subprocess.check_output(['python3', 'tools/gen_embed.py', str(patched), str(gen / 'embed.S'), 'main', 'subsdk0', 'sdk'], cwd=ios, env=env).decode().strip()
(gen / 'dm.xcconfig').write_text(build_config + '\nOTHER_LDFLAGS = $(inherited) $(DM_FRAMEWORKS) ' + flags + '\n')
shutil.copytree(base_app / 'dm', gen / 'dm')
shutil.copyfile(patched / 'main.fixups.tsv', gen / 'dm/main.fixups.tsv')
run(['python3', source / 'dm/games/settings.py', env['GAME'], patched, output / 'no-control.nacp', gen / 'dm/launcher.json'])
launcher = json.loads((gen / 'dm/launcher.json').read_text())
original_launcher = json.loads((base_app / 'dm/launcher.json').read_text())
# Preserve the NACP-derived language choices from the verified original package.
for i, row in enumerate(original_launcher['settings']):
    if row['env'] == 'DM_LANG' and not any(s['env'] == 'DM_LANG' for s in launcher['settings']):
        launcher['settings'].insert(min(i, len(launcher['settings'])), row)
(gen / 'dm/launcher.json').write_text(json.dumps(launcher, ensure_ascii=False, indent=1) + '\n')
settings = {s['env']: s for s in launcher['settings']}
assert settings['DM_SCREEN_RESOLUTION']['default'] == '960x540'
assert [p[0] for p in settings['DM_SCREEN_RESOLUTION']['options']] == ['native', '1280x720', '960x540', '640x360']
assert settings['DM_OPMODE']['default'] == '0' and settings['DM_FPS_TARGET']['default'] == '30'
assert (gen / 'dm/env.txt').read_bytes() == (source / 'dm/games/0100000011D90000/ios.env').read_bytes()
chain = manifest['shader_chain']
assert '#define DMSH_CHAIN "' + chain + '"' in (source / 'dm/gfx/nvn/dmsh_chain.h').read_text()
(gen / 'Assets.xcassets').mkdir()
(gen / 'Assets.xcassets/Contents.json').write_text('{"info":{"author":"xcode","version":1}}\n')
run(['xcodegen', 'generate', '-q'], cwd=ios)
derived = output / 'derived'
command = ['xcodebuild', '-project', 'DmIOS.xcodeproj', '-scheme', 'DmIOS', '-configuration', 'Release',
           '-destination', 'generic/platform=iOS', '-derivedDataPath', str(derived),
           'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', 'CODE_SIGN_IDENTITY=',
           'DM_COPY_GAME_RESOURCES=NO', 'DM_XCODE_OUTPUT_ROOT=' + str(derived),
           'SYMROOT=' + str(derived / 'Build/Products'), 'OBJROOT=' + str(derived / 'Build/Intermediates.noindex'), 'build']
with (output / 'xcodebuild.log').open('w') as log:
    result = subprocess.run(command, cwd=ios, env=env, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    lines = (output / 'xcodebuild.log').read_text(errors='replace').splitlines()
    print('\n'.join(line for line in lines if 'error:' in line)[-6000:])
    raise SystemExit(result.returncode)
app = derived / 'Build/Products/Release-iphoneos/DmIOS.app'
assert (app / 'DmIOS').is_file()
base_info = plistlib.loads((base_app / 'Info.plist').read_bytes())
info = plistlib.loads((app / 'Info.plist').read_bytes())
for key in ('CFBundleIcons', 'CFBundleIcons~ipad'):
    info[key] = base_info[key]
info['CFBundleVersion'] = '1.3.6'
info['DMBuildRevision'] = 'r6'
assert info['CFBundleIdentifier'] == base_info['CFBundleIdentifier']
assert info['MinimumOSVersion'] == '16.1' and info['CFBundleShortVersionString'] == '1.3.0'
(app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
for name in ('Assets.car', 'AppIcon60x60@2x.png', 'AppIcon76x76@2x~ipad.png'):
    shutil.copyfile(base_app / name, app / name)
# Carry the original package's entitlement request using the upstream packer's
# ad-hoc executable signature. No identity, certificate or device is used.
entitlements = subprocess.run(['codesign', '-d', '--entitlements', ':-', str(base_app / 'DmIOS')], capture_output=True, check=True).stdout
values = plistlib.loads(entitlements)
assert values.get('com.apple.developer.kernel.increased-memory-limit') is True
ent = output / 'DmIOS.entitlements'
ent.write_bytes(plistlib.dumps(values))
run(['codesign', '--force', '--sign', '-', '--entitlements', ent, app / 'DmIOS'])
binary = (app / 'DmIOS').read_bytes()
assert b'Unity screen resolution request %dx%d' in binary
assert b'[resolution-probe]' not in binary and b'[motion-capture]' not in binary
delta = output / 'r6-host-delta.zip'
replacements = {}
with zipfile.ZipFile(delta, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in sorted(app.rglob('*')):
        if not p.is_file() or '_CodeSignature' in p.parts:
            continue
        relative = p.relative_to(app).as_posix()
        assert not relative.startswith(('msl/', 'romfs', 'aoc/', 'pso/'))
        data = p.read_bytes()
        replacements['Payload/DmIOS.app/' + relative] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        z.writestr('Payload/DmIOS.app/' + relative, data)
record = {'revision': 'r6', 'run': os.environ['GITHUB_RUN_ID'], 'config_commit': os.environ['GITHUB_SHA'],
          'base_ipa_sha256': manifest['base_ipa_sha256'], 'shader_chain': chain,
          'delta_sha256': hashlib.sha256(delta.read_bytes()).hexdigest(), 'delta_size': delta.stat().st_size,
          'production_source_sha256': production_hash, 'module_sha256': module_hashes,
          'defaults': {'DM_OPMODE': '0', 'DM_FPS_TARGET': '30', 'DM_SCREEN_RESOLUTION': '960x540'},
          'replacements': replacements, 'visual_validation': proof,
          'patch_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((config / 'patches').glob('*.patch'))},
          'device_gameplay_verified': False, 'phone_power_verified': False}
(output / 'r6-host-delta.json').write_text(json.dumps(record, indent=2) + '\n')
print('Unsigned iOS 16 host rebuild passed; private delta bytes:', delta.stat().st_size)
