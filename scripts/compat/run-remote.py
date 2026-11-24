#!/usr/bin/env python3
"""Snapshot the current sources and run compatibility checks on an ARM64 host."""
import argparse
import codecs
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

import paramiko


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def execute(client, command, timeout=900, check=True):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    # Drain both streams together so a large compiler diagnostic cannot block SSH.
    channel = stdout.channel
    collected = []
    streams = [(channel.recv_ready, channel.recv, codecs.getincrementaldecoder('utf-8')('replace')),
               (channel.recv_stderr_ready, channel.recv_stderr, codecs.getincrementaldecoder('utf-8')('replace'))]
    deadline = time.monotonic() + timeout
    while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
        if time.monotonic() > deadline:
            channel.close()
            raise subprocess.TimeoutExpired(command, timeout, output=''.join(collected))
        for ready, read, decoder in streams:
            if ready():
                text = decoder.decode(read(65536))
                print(text, end='', flush=True)
                collected.append(text)
        time.sleep(0.05)
    code = channel.recv_exit_status()
    for _, _, decoder in streams:
        collected.append(decoder.decode(b'', final=True))
    output = ''.join(collected)
    if code and check:
        raise subprocess.CalledProcessError(code, command, output=output)
    return subprocess.CompletedProcess(command, code, output)


def source_archive(repository, bundle):
    with bundle.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for folder in ('scripts', 'native', 'tools', 'java', 'docs'):
                for path in sorted((repository / folder).rglob('*')):
                    if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                        continue
                    info = archive.gettarinfo(str(path), 'source/' + path.relative_to(repository).as_posix())
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mode &= 0o755
                    with path.open('rb') as content:
                        archive.addfile(info, content)


EXTRACT = r'''
import errno, hashlib, os, pathlib, shutil, sys, tarfile, tempfile
archive, destination, expected = sys.argv[1:]
archive = pathlib.Path(archive)
destination = pathlib.Path(destination)
value = hashlib.sha256()
with archive.open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        value.update(block)
assert value.hexdigest() == expected, 'Uploaded archive digest differs'
marker = destination / 'input-sha256'
if destination.exists():
    assert marker.read_text().strip() == expected, 'Existing snapshot identity differs'
else:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    staging = pathlib.Path(tempfile.mkdtemp(prefix='.' + destination.name + '-', dir=destination.parent))
    try:
        with tarfile.open(archive) as source:
            source.extractall(staging, filter='data')
        (staging / 'input-sha256').write_text(expected + '\n')
        try:
            os.rename(staging, destination)
        except OSError as failure:
            if failure.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            assert marker.read_text().strip() == expected, 'Concurrent snapshot identity differs'
    finally:
        if staging.exists():
            assert staging.resolve().parent == destination.parent.resolve()
            shutil.rmtree(staging)
# The data filter intentionally discards directory modes. Restore archive read
# and execute permissions so an ordinary-user ART can traverse a root-owned copy.
destination.parent.chmod(0o755)
destination.chmod(0o755)
with tarfile.open(archive) as source:
    for member in source:
        target = destination / member.name
        assert target.resolve().is_relative_to(destination.resolve()), 'Snapshot path escapes root'
        if member.isdir() or member.isfile():
            target.chmod(member.mode & 0o755)
        if member.isfile():
            with source.extractfile(member) as original, target.open('rb') as extracted:
                original_hash = hashlib.file_digest(original, 'sha256').hexdigest()
                extracted_hash = hashlib.file_digest(extracted, 'sha256').hexdigest()
                assert original_hash == extracted_hash, 'Extracted snapshot file differs: ' + member.name
print('SNAPSHOT_READY ' + str(destination))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='ubuntu')
    parser.add_argument('--password-env', default='SAILDROID_TEST_PASSWORD')
    parser.add_argument('--ignore-host-key', action='store_true')
    parser.add_argument('--workspace', default='/home/ubuntu/saildroid-compat')
    parser.add_argument('--payload', type=Path, required=True, help='RPM payload.tar')
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--r8', type=Path, required=True)
    parser.add_argument('--input', type=Path, action='append', default=[])
    parser.add_argument('--apk', type=Path, action='append', default=[])
    parser.add_argument('--no-elf', action='store_true')
    parser.add_argument('--label', default=time.strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    arguments = parser.parse_args()
    workspace = PurePosixPath(arguments.workspace)
    if not workspace.is_absolute() or '..' in workspace.parts or workspace == PurePosixPath('/'):
        parser.error('An absolute dedicated workspace is required')
    if not arguments.label or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in arguments.label):
        parser.error('The run label must contain letters, digits, hyphens or underscores')
    if arguments.output.exists():
        parser.error('Output directory already exists')
    password = os.environ.get(arguments.password_env)
    if password is None:
        parser.error('Set the requested SSH password environment variable')
    arguments.output.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[2]
    client = paramiko.SSHClient()
    sftp = None
    if arguments.ignore_host_key:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.load_system_host_keys()
    try:
        client.connect(arguments.host, username=arguments.user, password=password,
                       timeout=15, allow_agent=False, look_for_keys=False)
        execute(client, 'test "$(uname -m)" = aarch64 && mkdir -p ' +
                shlex.quote(str(workspace / 'inputs')))
        sftp = client.open_sftp()

        def upload(path, name=None):
            sha = digest(path)
            remote = str(workspace / 'inputs' / (sha + '-' + (name or path.name)))
            try:
                current = sftp.stat(remote)
            except FileNotFoundError:
                current = None
            valid = False
            if current is not None and current.st_size == path.stat().st_size:
                verified = execute(client, 'python3 -c ' + shlex.quote(
                    'import hashlib,sys; h=hashlib.file_digest(open(sys.argv[1],"rb"),"sha256"); '
                    'sys.exit(0 if h.hexdigest()==sys.argv[2] else 1)') + ' ' + shlex.quote(remote) + ' ' + sha,
                    check=False)
                valid = verified.returncode == 0
            if not valid:
                print('UPLOADING ' + path.name, flush=True)
                staging = remote + '.upload-' + uuid.uuid4().hex
                try:
                    sftp.put(str(path), staging)
                    commit = 'import hashlib,os,pathlib,sys; p=pathlib.Path(sys.argv[1]); '
                    commit += 'target=pathlib.Path(sys.argv[2]); assert p.parent.resolve()==target.parent.resolve(); '
                    commit += 'h=hashlib.file_digest(p.open("rb"),"sha256"); assert h.hexdigest()==sys.argv[3]; os.replace(p,target)'
                    execute(client, 'python3 -c ' + shlex.quote(commit) + ' ' +
                            ' '.join(shlex.quote(part) for part in (staging, remote, sha)))
                finally:
                    try:
                        sftp.remove(staging)
                    except FileNotFoundError:
                        pass
            return remote, sha

        payload, payload_sha = upload(arguments.payload)
        runtime = workspace / 'runtimes' / payload_sha
        execute(client, 'sudo -n python3 -c ' + shlex.quote(EXTRACT) + ' ' +
                ' '.join(shlex.quote(str(p)) for p in (payload, runtime, payload_sha)))
        with tempfile.TemporaryDirectory(prefix='saildroid-compat-source-') as temporary:
            bundle = Path(temporary) / 'sources.tar.gz'
            source_archive(repository, bundle)
            uploaded, source_sha = upload(bundle)
            source = workspace / 'sources' / source_sha
            execute(client, 'python3 -c ' + shlex.quote(EXTRACT) + ' ' +
                    ' '.join(shlex.quote(str(p)) for p in (uploaded, source, source_sha)))
        framework, _ = upload(arguments.framework)
        r8, _ = upload(arguments.r8)
        extra_inputs = [upload(path)[0] for path in arguments.input]
        apks = [upload(path)[0] for path in arguments.apk]
        remote_output = workspace / 'results' / arguments.label
        record = dict(host=arguments.host, machine='aarch64', workspace=str(workspace),
                      source=str(source / 'source'), source_sha256=source_sha,
                      runtime=str(runtime / 'payload'), payload_sha256=payload_sha,
                      framework=framework, r8=r8, extra_inputs=extra_inputs,
                      apks=apks, output=str(remote_output))
        (arguments.output / 'remote-inputs.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        if arguments.prepare_only:
            print('REMOTE_PREPARED ' + str(arguments.output / 'remote-inputs.json'))
            return 0
        command = ['python3', str(source / 'source/scripts/compat/run-preflight.py'),
                   '--runtime-root', record['runtime'], '--framework', framework,
                   '--r8', r8, '--output', str(remote_output), '--headless']
        for apk in apks:
            command.extend(['--apk', apk])
        if not arguments.no_elf:
            command.append('--elf')
        execute(client, 'test ! -e ' + shlex.quote(str(remote_output)))
        execution = None
        collection_errors = []
        try:
            execution = execute(client, 'timeout --kill-after=10s 1700s ' +
                                ' '.join(shlex.quote(part) for part in command), timeout=1800, check=False)
            (arguments.output / 'remote.log').write_text(execution.stdout, encoding='utf-8')
        except subprocess.TimeoutExpired as failure:
            (arguments.output / 'remote.log').write_text(failure.output or '', encoding='utf-8')
            raise
        finally:
            def collect(remote_folder, local_folder):
                local_folder.mkdir(parents=True, exist_ok=True)
                for entry in sftp.listdir_attr(str(remote_folder)):
                    remote_path = remote_folder / entry.filename
                    local_path = local_folder / entry.filename
                    if stat.S_ISDIR(entry.st_mode):
                        collect(remote_path, local_path)
                    elif stat.S_ISREG(entry.st_mode):
                        sftp.get(str(remote_path), str(local_path))
            try:
                collect(remote_output, arguments.output / 'results')
            except Exception as failure:
                collection_errors.append(dict(type=type(failure).__name__, message=str(failure)))
            outcome = dict(returncode=execution.returncode if execution else None,
                           collection_errors=collection_errors)
            (arguments.output / 'remote-run.json').write_text(json.dumps(outcome, indent=2) + '\n', encoding='utf-8')
        return execution.returncode or (3 if collection_errors else 0)
    except Exception as failure:
        error = dict(type=type(failure).__name__, message=str(failure))
        (arguments.output / 'remote-error.json').write_text(json.dumps(error, indent=2) + '\n', encoding='utf-8')
        if isinstance(failure, subprocess.CalledProcessError):
            (arguments.output / 'remote-error.log').write_text(failure.stdout or '', encoding='utf-8')
        raise
    finally:
        if sftp:
            sftp.close()
        client.close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
