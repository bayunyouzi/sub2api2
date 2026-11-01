#!/usr/bin/env python3
"""Install the controller on the existing migrated host; keep deployment disabled."""
import datetime
import json
import os
import pathlib
import shutil
import subprocess

os.umask(0o077)
root = pathlib.Path('/opt/zeabur-migration')
work = root / 'autodeploy'
source = pathlib.Path(__file__).resolve().parent
if os.geteuid() != 0 or not (root / 'compose.json').exists():
    raise SystemExit('Run as root on the existing migrated host')
work.mkdir(mode=0o700, exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = work / ('install-backup-' + stamp)
backup.mkdir(mode=0o700)
site = pathlib.Path('/etc/nginx/sites-enabled/zeabur-migration.conf').resolve(strict=True)
files = [root / 'nginx.conf', site, root / 'backup.py']
for index, path in enumerate(files):
    shutil.copy2(path, backup / (str(index) + '-' + path.name))
needle = '    location / {\n        proxy_pass http://127.0.0.1:8443;'
replacement = ('    location / {\n'
               '        if (-f /var/www/zeabur-public/sub2api-maintenance) { return 503; }\n'
               '        proxy_pass http://127.0.0.1:8443;')
try:
    for path in files[:2]:
        text = path.read_text()
        if replacement not in text:
            if text.count(needle) != 1:
                raise RuntimeError('Unexpected Nginx layout; inspect before installation')
            path.write_text(text.replace(needle, replacement))
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
except BaseException:
    for index, path in enumerate(files[:2]):
        shutil.copy2(backup / (str(index) + '-' + path.name), path)
    raise
for name in ('autodeploy.py', 'install.py', 'sub2api-autodeploy.service', 'sub2api-autodeploy.timer'):
    if (source / name).resolve() != (work / name).resolve():
        shutil.copy2(source / name, work / name)
    os.chmod(work / name, 0o600)
for name in ('sub2api-autodeploy.service', 'sub2api-autodeploy.timer'):
    shutil.copyfile(work / name, pathlib.Path('/etc/systemd/system') / name)
    os.chmod(pathlib.Path('/etc/systemd/system') / name, 0o644)
if not (work / 'config.json').exists():
    (work / 'config.json').write_text(json.dumps({'enabled': False}, indent=2) + '\n')
backup_script = root / 'backup.py'
text = backup_script.read_text()
if "'autodeploy/autodeploy.py'" not in text:
    needle = "'cloudflare-realip.conf'):"
    replacement = "'cloudflare-realip.conf','autodeploy/autodeploy.py','autodeploy/install.py','autodeploy/config.json','autodeploy/state.json','autodeploy/sub2api-autodeploy.service','autodeploy/sub2api-autodeploy.timer'):"
    if text.count(needle) != 1:
        raise RuntimeError('Unexpected daily backup layout')
    backup_script.write_text(text.replace(needle, replacement))
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemd-analyze', 'verify', '/etc/systemd/system/sub2api-autodeploy.service', '/etc/systemd/system/sub2api-autodeploy.timer'], check=True)
print('Installed. Deployment remains disabled until config.json enabled is set to true.')
