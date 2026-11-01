#!/usr/bin/env python3
"""Deploy published main images to the existing, private Compose installation."""
import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path('/opt/zeabur-migration')
WORK = ROOT / 'autodeploy'
MAINTENANCE = pathlib.Path('/var/www/zeabur-public/sub2api-maintenance')
REPOSITORY = 'bayunyouzi/sub2api2'
IMAGE_PREFIX = 'bayunzi/sub2api-main:sha-'
os.umask(0o077)


def write_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    with temporary.open('rb') as stream:
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def log(message):
    print(dt.datetime.now(dt.timezone.utc).isoformat(), message, flush=True)


def run(args, *, input_file=None, output_file=None, check=True, timeout=600):
    with open(WORK / 'commands.log', 'ab') as private_log:
        source = open(input_file, 'rb') if input_file else None
        destination = open(output_file, 'wb') if output_file else subprocess.PIPE
        try:
            result = subprocess.run(args, stdin=source, stdout=destination,
                                    stderr=private_log, timeout=timeout)
        finally:
            if source:
                source.close()
            if output_file:
                destination.close()
        if check and result.returncode:
            raise RuntimeError('Command failed: ' + ' '.join(args[:5]))
        return result


def compose(*args, config=None, project=None, **kwargs):
    command = ['docker', 'compose', '-f', str(config or ROOT / 'compose.json')]
    if project:
        command += ['--project-name', project]
    return run(command + list(args), **kwargs)


def container(service='sub2api', **kwargs):
    return compose('ps', '-q', service, **kwargs).stdout.decode().strip()


def maintenance(enabled):
    if enabled:
        MAINTENANCE.write_text('Sub2API update in progress\n')
        os.chmod(MAINTENANCE, 0o644)
    else:
        MAINTENANCE.unlink(missing_ok=True)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def github_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'bayunzi-sub2api-autodeploy',
                                                 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read(2 * 1024 * 1024))


def published_bundle():
    head = github_json(f'https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main')['object']['sha']
    if not re.fullmatch('[0-9a-f]{40}', head):
        raise RuntimeError('Invalid main revision')
    state = read_json(WORK / 'state.json', {})
    if head in (state.get('deployed_revision'), state.get('failed_revision')):
        return None
    try:
        release = github_json(f'https://api.github.com/repos/{REPOSITORY}/releases/tags/deploy-main-{head}')
    except urllib.error.HTTPError as error:
        if error.code == 404:
            log('Waiting for a tested deployment bundle for ' + head[:12])
            return None
        raise
    if release.get('draft') or release.get('target_commitish') != head:
        raise RuntimeError('Deployment release does not match main')
    assets = {item['name']: item for item in release['assets']}
    expected = f'https://github.com/{REPOSITORY}/releases/download/deploy-main-{head}/'
    for name in ('metadata.json', 'image.tar.gz'):
        if name not in assets or assets[name]['browser_download_url'] != expected + name:
            raise RuntimeError('Missing or unexpected deployment asset')
    with urllib.request.urlopen(assets['metadata.json']['browser_download_url'], timeout=30) as response:
        metadata = json.loads(response.read(16384))
    if (metadata.get('schema_version') != 1 or metadata.get('repository') != REPOSITORY
            or metadata.get('revision') != head or metadata.get('image') != IMAGE_PREFIX + head
            or not re.fullmatch('sha256:[0-9a-f]{64}', metadata.get('image_id', ''))
            or not re.fullmatch('[0-9a-f]{64}', metadata.get('sha256', ''))
            or not isinstance(metadata.get('size'), int) or not 0 < metadata['size'] < 1024**3
            or assets['image.tar.gz']['size'] != metadata['size']):
        raise RuntimeError('Invalid deployment metadata')
    return metadata, assets['image.tar.gz']['browser_download_url']


def load_bundle(metadata, url):
    archive = WORK / 'image.tar.gz'
    if not archive.exists() or archive.stat().st_size != metadata['size'] or digest(archive) != metadata['sha256']:
        partial = archive.with_suffix('.partial')
        with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as output:
            received = 0
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > metadata['size']:
                    raise RuntimeError('Deployment archive exceeds its declared size')
                output.write(chunk)
        if partial.stat().st_size != metadata['size'] or digest(partial) != metadata['sha256']:
            raise RuntimeError('Deployment archive checksum mismatch')
        partial.replace(archive)
    run(['docker', 'image', 'load', '-i', str(archive)], timeout=600)
    image = json.loads(run(['docker', 'image', 'inspect', metadata['image']]).stdout)[0]
    labels = image.get('Config', {}).get('Labels', {}) or {}
    if (image['Id'] != metadata['image_id'] or image['Architecture'] != 'amd64' or image['Os'] != 'linux'
            or labels.get('org.opencontainers.image.source') != 'https://github.com/' + REPOSITORY
            or labels.get('org.opencontainers.image.revision') != metadata['revision']):
        raise RuntimeError('Loaded image identity does not match the deployment metadata')


def require_configuration(configuration):
    environment = configuration['services']['sub2api']['environment']
    if not isinstance(environment, dict) or not environment.get('TOTP_ENCRYPTION_KEY'):
        raise RuntimeError('The persistent TOTP encryption key must be retained')
    if environment.get('DATABASE_HOST') != 'postgres' or environment.get('REDIS_HOST') != 'redis':
        raise RuntimeError('Unexpected production database endpoints')
    if configuration['services']['sub2api']['volumes'] != ['./data/sub2api:/app/data']:
        raise RuntimeError('Unexpected application data mount')


def dump_database(path):
    compose('exec', '-T', 'postgres', 'pg_dump', '-U', 'root', '-d', 'zeabur', '-Fc', '--create',
            output_file=path, timeout=1800)


def wait_for_app(expected_image=None, *, config=None, project=None, seconds=300):
    successes = 0
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        identifier = container(config=config, project=project)
        if identifier:
            inspection = json.loads(run(['docker', 'inspect', identifier]).stdout)[0]
            if expected_image and inspection['Image'] != expected_image:
                raise RuntimeError('Unexpected running application image')
            if inspection['State']['Status'] in ('exited', 'dead'):
                raise RuntimeError('Application exited during startup')
            health = run(['docker', 'exec', identifier, 'wget', '-q', '-T', '5', '-O', '-',
                          'http://127.0.0.1:443/health'], check=False, timeout=15)
            page = run(['docker', 'exec', identifier, 'wget', '-q', '-T', '5', '-O', '-',
                        'http://127.0.0.1:443/login'], check=False, timeout=15)
            if (health.returncode == 0 and b'"status":"ok"' in health.stdout
                    and page.returncode == 0 and b'<html' in page.stdout.lower()):
                successes += 1
                if successes >= 3:
                    return
            else:
                successes = 0
        time.sleep(2)
    raise RuntimeError('Application startup checks timed out')


def isolated_volumes(service, volumes, test_root):
    result = []
    for volume in volumes:
        source, destination, *options = volume.split(':')
        if source == './data/' + service:
            replacement = test_root / 'data' / service
        elif source.startswith('./config/') and options == ['ro']:
            original = ROOT / source
            if original.is_symlink() or not original.is_file() or not original.resolve().is_relative_to((ROOT / 'config').resolve()):
                raise RuntimeError('Unexpected preflight configuration file')
            replacement = test_root / 'config' / (service + '-' + original.name)
            replacement.parent.mkdir(mode=0o700, exist_ok=True)
            shutil.copyfile(original, replacement)
        else:
            raise RuntimeError('Unsupported preflight volume layout')
        result.append(':'.join([str(replacement), destination] + options))
    return result


def preflight(metadata, configuration):
    """Apply migrations to an isolated copy before interrupting production."""
    test_root = WORK / 'preflight'
    if test_root.exists():
        raise RuntimeError('An earlier preflight directory needs recovery')
    test_root.mkdir(mode=0o700)
    test_config = test_root / 'compose.json'
    project = 'sub2api-preflight'
    try:
        shutil.copytree(ROOT / 'data/sub2api', test_root / 'data/sub2api', ignore=shutil.ignore_patterns('logs'))
        services = {}
        for service in ('postgres', 'redis', 'sub2api'):
            value = copy.deepcopy(configuration['services'][service])
            for key in ('ports', 'container_name', 'hostname', 'depends_on', 'profiles'):
                value.pop(key, None)
            value['restart'] = 'no'
            value['networks'] = ['isolated']
            value['mem_limit'] = {'postgres': '640m', 'redis': '256m', 'sub2api': '1024m'}[service]
            value['cpus'] = 1
            value['volumes'] = isolated_volumes(service, value.get('volumes', []), test_root)
            if service == 'sub2api':
                value['image'] = metadata['image']
                value['environment']['SERVER_PORT'] = '443'
                value['environment']['SERVER_HOST'] = '0.0.0.0'
                value['environment']['DATABASE_DBNAME'] = 'zeabur'
            services[service] = value
        write_json(test_config, {'services': services, 'networks': {'isolated': {'internal': True}}})
        dump_database(test_root / 'zeabur.dump')
        compose('up', '-d', '--pull', 'never', 'postgres', 'redis', config=test_config, project=project)
        for attempt in range(60):
            ready = compose('exec', '-T', 'postgres', 'pg_isready', '-h', '127.0.0.1', '-U', 'root',
                            config=test_config, project=project, check=False)
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Preflight database failed to start')
        compose('exec', '-T', 'postgres', 'pg_restore', '-U', 'root', '--exit-on-error', '--clean',
                '--if-exists', '--create', '-d', 'postgres', input_file=test_root / 'zeabur.dump',
                config=test_config, project=project, timeout=1800)
        compose('up', '-d', '--no-deps', '--pull', 'never', 'sub2api', config=test_config, project=project)
        wait_for_app(metadata['image_id'], config=test_config, project=project)
        log('Isolated database migration and startup checks passed')
    finally:
        if test_config.exists():
            cleanup = compose('down', '--timeout', '10', config=test_config, project=project,
                              check=False, timeout=120)
            if cleanup.returncode:
                raise RuntimeError('Preflight containers could not be cleaned up')
        if test_root.resolve().parent != WORK.resolve() or test_root.is_symlink():
            raise RuntimeError('Unsafe preflight cleanup path')
        shutil.rmtree(test_root)


def snapshot(directory):
    dump_database(directory / 'zeabur.dump')
    compose('exec', '-T', 'redis', 'sh', '-c',
            'export REDISCLI_AUTH="$REDIS_PASSWORD"; redis-cli --rdb /tmp/autodeploy.rdb >/dev/null && cat /tmp/autodeploy.rdb',
            output_file=directory / 'redis.rdb', timeout=600)
    with tarfile.open(directory / 'sub2api-data.tar.gz', 'w:gz') as archive:
        for item in (ROOT / 'data/sub2api').iterdir():
            if item.name != 'logs':
                archive.add(item, arcname=item.name)
    manifest = {name: digest(directory / name) for name in
                ('compose.before.json', 'state.before.json', 'zeabur.dump', 'redis.rdb', 'sub2api-data.tar.gz')}
    write_json(directory / 'manifest.json', manifest)
    (directory / 'COMPLETE').write_text('Complete, with the production application stopped\n')
    os.sync()


def restore(directory):
    if not (directory / 'COMPLETE').exists():
        raise RuntimeError('Refusing to restore an incomplete snapshot')
    for name, checksum in read_json(directory / 'manifest.json').items():
        if name not in ('compose.before.json', 'state.before.json', 'zeabur.dump', 'redis.rdb', 'sub2api-data.tar.gz') or digest(directory / name) != checksum:
            raise RuntimeError('Snapshot checksum validation failed')
    compose('exec', '-T', 'postgres', 'psql', '-U', 'root', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c',
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='zeabur' AND pid<>pg_backend_pid()")
    compose('exec', '-T', 'postgres', 'pg_restore', '-U', 'root', '--exit-on-error', '--clean',
            '--if-exists', '--create', '-d', 'postgres', input_file=directory / 'zeabur.dump', timeout=1800)
    compose('stop', '--timeout', '15', 'redis')
    redis_root = ROOT / 'data/redis'
    old_rdb = redis_root / 'dump.rdb'
    original_stat = old_rdb.stat()
    destination = redis_root / 'dump.rdb.restore'
    shutil.copyfile(directory / 'redis.rdb', destination)
    os.chown(destination, original_stat.st_uid, original_stat.st_gid)
    os.chmod(destination, original_stat.st_mode & 0o777)
    destination.replace(old_rdb)
    app_root = ROOT / 'data/sub2api'
    failed_root = directory / 'failed-app-data'
    if app_root.exists():
        if failed_root.exists():
            if app_root.is_symlink() or app_root.resolve() != ROOT.resolve() / 'data/sub2api':
                raise RuntimeError('Unsafe application data recovery path')
            shutil.rmtree(app_root)
        else:
            app_root.rename(failed_root)
    app_root.mkdir(mode=0o700)
    with tarfile.open(directory / 'sub2api-data.tar.gz') as archive:
        archive.extractall(app_root, filter='data')
    compose('up', '-d', '--no-deps', '--pull', 'never', 'redis')


def recover(transaction):
    directory = pathlib.Path(transaction['snapshot'])
    if directory.resolve().parent != (WORK / 'snapshots').resolve() or directory.is_symlink():
        raise RuntimeError('Invalid snapshot recovery path')
    if transaction['phase'] == 'committed':
        maintenance(False)
        (WORK / 'transaction.json').unlink(missing_ok=True)
        return
    maintenance(True)
    compose('stop', '--timeout', '120', 'sub2api')
    if transaction['phase'] in ('deploying', 'restoring'):
        transaction['phase'] = 'restoring'
        write_json(WORK / 'transaction.json', transaction)
        restore(directory)
    write_json(ROOT / 'compose.json', read_json(directory / 'compose.before.json'))
    compose('up', '-d', '--no-deps', '--pull', 'never', 'sub2api')
    wait_for_app(transaction['old_image_id'])
    state = read_json(directory / 'state.before.json', {})
    state.update(failed_revision=transaction['revision'], last_result='rolled_back',
                 last_snapshot=str(directory))
    write_json(WORK / 'state.json', state)
    maintenance(False)
    (WORK / 'transaction.json').unlink(missing_ok=True)
    log('Previous application and snapshot restored; failed revision will not be retried')


def activate(metadata, configuration):
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = WORK / 'snapshots' / (stamp + '-' + metadata['revision'][:12])
    directory.mkdir(mode=0o700, parents=True)
    write_json(directory / 'compose.before.json', configuration)
    write_json(directory / 'state.before.json', read_json(WORK / 'state.json', {}))
    identifier = container()
    old_image = json.loads(run(['docker', 'inspect', identifier]).stdout)[0]['Image']
    transaction = {'phase': 'preparing', 'snapshot': str(directory),
                   'revision': metadata['revision'], 'old_image_id': old_image}
    write_json(WORK / 'transaction.json', transaction)
    try:
        maintenance(True)
        compose('stop', '--timeout', '120', 'sub2api')
        snapshot(directory)
        updated = copy.deepcopy(configuration)
        app = updated['services']['sub2api']
        app['image'] = metadata['image']
        app['pull_policy'] = 'never'
        app['environment'].update(SERVER_PORT='443', SERVER_HOST='0.0.0.0', DATABASE_DBNAME='zeabur')
        transaction['phase'] = 'deploying'
        write_json(WORK / 'transaction.json', transaction)
        write_json(ROOT / 'compose.json', updated)
        compose('up', '-d', '--no-deps', '--pull', 'never', 'sub2api')
        wait_for_app(metadata['image_id'])
        state = read_json(WORK / 'state.json', {})
        state.update(deployed_revision=metadata['revision'], deployed_version=metadata['version'],
                     deployed_image_id=metadata['image_id'], last_snapshot=str(directory),
                     last_result='success', deployed_at=dt.datetime.now(dt.timezone.utc).isoformat())
        state.pop('failed_revision', None)
        write_json(WORK / 'state.json', state)
        transaction['phase'] = 'committed'
        write_json(WORK / 'transaction.json', transaction)
        maintenance(False)
        (WORK / 'transaction.json').unlink(missing_ok=True)
        log('Deployed ' + metadata['version'] + ' at ' + metadata['revision'][:12])
    except BaseException:
        log('Deployment failed; recovering before accepting new public requests')
        try:
            recover(read_json(WORK / 'transaction.json', transaction))
        except BaseException:
            (WORK / 'PAUSED').write_text('Recovery needs operator attention; maintenance is retained\n')
            log('Recovery failed; automatic updates paused, maintenance retained')
            raise
        raise


def prune_snapshots():
    state = read_json(WORK / 'state.json', {})
    base = WORK / 'snapshots'
    if not base.exists():
        return
    snapshots = sorted((item for item in base.iterdir() if item.is_dir()
                        and not item.is_symlink() and (item / 'COMPLETE').exists()), reverse=True)
    keep = set(snapshots[:3])
    if state.get('last_snapshot'):
        keep.add(pathlib.Path(state['last_snapshot']))
    keep_image_ids = {state.get('deployed_image_id')}
    for item in snapshots:
        if item in keep:
            old = read_json(item / 'compose.before.json')['services']['sub2api']['image']
            info = run(['docker', 'image', 'inspect', old], check=False)
            if info.returncode == 0:
                keep_image_ids.add(json.loads(info.stdout)[0]['Id'])
        else:
            if item.resolve().parent != base.resolve():
                raise RuntimeError('Unsafe snapshot retention path')
            shutil.rmtree(item)
    listing = run(['docker', 'image', 'ls', '--no-trunc', '--format', '{{json .}}', 'bayunzi/sub2api-main']).stdout.decode()
    for line in listing.splitlines():
        image = json.loads(line)
        if re.fullmatch('sha-[0-9a-f]{40}', image['Tag']) and image['ID'] not in keep_image_ids:
            run(['docker', 'image', 'rm', 'bayunzi/sub2api-main:' + image['Tag']], check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Read configuration and published version without deploying')
    parser.add_argument('--recover', action='store_true', help='Resume an interrupted recovery, even when paused')
    args = parser.parse_args()
    WORK.mkdir(mode=0o700, exist_ok=True)
    lock = open('/run/sub2api-autodeploy.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('Another deployment is already running')
        return
    if args.check:
        require_configuration(read_json(ROOT / 'compose.json'))
        bundle = published_bundle()
        log('Published revision: ' + (bundle[0]['revision'] if bundle else 'no pending bundle'))
        return
    if (WORK / 'PAUSED').exists() and not args.recover:
        log('Automatic deployment is paused')
        return
    transaction = read_json(WORK / 'transaction.json')
    if transaction:
        recover(transaction)
        return
    if args.recover:
        log('There is no interrupted deployment to recover')
        return
    if not read_json(WORK / 'config.json', {}).get('enabled'):
        log('Automatic deployment is disabled')
        return
    bundle = published_bundle()
    if not bundle:
        return
    if shutil.disk_usage(ROOT).free < 8 * 1024**3:
        raise RuntimeError('At least 8 GiB free disk space is required for safe deployment')
    metadata, url = bundle
    configuration = read_json(ROOT / 'compose.json')
    require_configuration(configuration)
    redis_persistence = compose('exec', '-T', 'redis', 'sh', '-c',
                                'export REDISCLI_AUTH="$REDIS_PASSWORD"; redis-cli --raw CONFIG GET appendonly dir dbfilename').stdout.decode()
    if 'appendonly\nno\n' not in redis_persistence or '/data\n' not in redis_persistence or 'dump.rdb\n' not in redis_persistence:
        raise RuntimeError('Redis persistence settings differ from the supported snapshot restore layout')
    load_bundle(metadata, url)
    backup_lock = open('/run/zeabur-migration-backup.lock', 'w')
    try:
        fcntl.flock(backup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('Daily backup is running; deployment deferred')
        return
    try:
        preflight(metadata, configuration)
    except Exception:
        state = read_json(WORK / 'state.json', {})
        state.update(failed_revision=metadata['revision'], last_result='preflight_failed')
        write_json(WORK / 'state.json', state)
        raise
    # A new push may have arrived while the image and migration checks were running.
    head = github_json(f'https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main')['object']['sha']
    if head != metadata['revision']:
        log('Main changed during preparation; deployment deferred')
        return
    activate(metadata, configuration)
    prune_snapshots()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        log(type(error).__name__ + ': ' + str(error))
        raise SystemExit(1)
