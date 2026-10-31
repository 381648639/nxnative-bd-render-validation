"""Keep diagnostic logs and screenshots in the private input repository only."""
import os
from pathlib import Path
import shutil
import subprocess

repo = os.environ['BD_ASSET_REPOSITORY']
tag = 'bd-visual-' + os.environ['GITHUB_RUN_ID']
evidence = Path('visual-evidence')
evidence.mkdir(exist_ok=True)
for logs in Path('game-input').glob('*_build/logs'):
    shutil.copytree(logs, evidence / 'build-logs', dirs_exist_ok=True)
subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--title',
                'Private renderer evidence ' + os.environ['GITHUB_RUN_ID'], '--notes',
                'Private game validation evidence. No device verdict is implied.', '--prerelease'],
               capture_output=True, check=False)
archive = Path(shutil.make_archive('private-visual-evidence', 'zip', evidence)).resolve()
subprocess.run(['gh', 'release', 'upload', tag, str(archive), '--repo', repo, '--clobber'], check=True)
