#!/usr/bin/env python3
"""Collect two authenticated binary ZIPs only after the exact complete run passes.

Prepared for explicit execution after review. No network or collection occurs
on import. The large binary TAR is inspected in streams, never extracted.
"""
from pathlib import Path
from datetime import datetime
import gzip
import hashlib
import json
import os
import posixpath
import re
import resource
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile

CONFIG = Path('/tmp/pdf-scene-candidate.json')
REPO = Path('/workspace/PDF-')
API = '/repos/vibracall-beep/PDF-'
REPO_ID = 1431437116
MAX_ARCHIVE = 12 * 1024**3
CHUNK = 1024 * 1024
BINARY_MEMBERS = {'PDF-arm64.tar.gz': MAX_ARCHIVE, 'PDF-arm64.tar.gz.sha256': 256,
                  'distribution-manifest.json': 32 * 1024**2, 'distribution-validation.json': 1024**2,
                  'install-binary.sh': 1024**2}
ROOT = SNAPSHOT = SHA = RUN = ATTEMPT = JOB_IDS = None


def require(condition, message):
    if not condition: raise ValueError(message)


def unique_json(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate JSON key: ' + key)
        value[key] = item
    return value


def invalid_constant(value):
    raise ValueError('Non-finite JSON constant: ' + value)


def parse_json(data):
    return json.loads(data, object_pairs_hook=unique_json, parse_constant=invalid_constant)


def open_regular(path, limit, *, empty=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = os.fdopen(descriptor, 'rb'); metadata = os.fstat(descriptor)
    try:
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                and (0 if empty else 1) <= metadata.st_size <= limit,
                'Expected bounded owned regular file: ' + path.name)
        return stream, metadata
    except BaseException:
        stream.close(); raise


def unchanged(stream, before):
    after = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'File changed during inspection.')


def read_regular(path, limit):
    stream, before = open_regular(path, limit)
    with stream:
        value = stream.read(limit + 1)
        require(len(value) == before.st_size, 'File changed while reading.')
        unchanged(stream, before)
    return value


def hash_regular(path, limit=MAX_ARCHIVE):
    stream, before = open_regular(path, limit)
    with stream:
        value = hash_stream(stream, before.st_size)
        unchanged(stream, before)
    return value


def hash_stream(stream, expected):
    digest = hashlib.sha256(); count = 0
    for block in iter(lambda: stream.read(CHUNK), b''):
        count += len(block); require(count <= expected, 'Stream exceeded its authenticated size.')
        digest.update(block)
    require(count == expected, 'Stream is truncated.')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def folder(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077,
            'Evidence directory must be private and owned.')


def write(path, data, *, replace=False):
    target = path.with_name(path.name + '.pending-' + str(os.getpid())) if replace else path
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    if replace:
        if os.path.lexists(path):
            before = path.lstat()
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), 'Existing evidence file is not owned/regular.')
        os.replace(target, path)


def encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def load_configuration():
    value = parse_json(read_regular(CONFIG, 16384))
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'sourceCommit', 'nativeRunID', 'runAttempt', 'jobIDs', 'outputDirectory'},
            'Complete explicit collector configuration is required.')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1, 'Unsupported configuration schema.')
    require(isinstance(value['sourceCommit'], str) and re.fullmatch('[0-9a-f]{40}', value['sourceCommit']), 'Exact source SHA required.')
    for key in ('nativeRunID', 'runAttempt'):
        require(type(value[key]) is int and 0 < value[key] < 2**63, 'Explicit positive ' + key + ' required.')
    require(isinstance(value['jobIDs'], dict) and set(value['jobIDs']) == {'macos-26', 'xcode-27'}
            and all(type(number) is int and 0 < number < 2**63 for number in value['jobIDs'].values())
            and len(set(value['jobIDs'].values())) == 2, 'Two explicit distinct job IDs required.')
    require(value['outputDirectory'] == '/workspace/.cache/pdf-native-' + value['sourceCommit'][:7],
            'Large binaries must use the shared dedicated /workspace/.cache evidence directory.')
    return value


def sanitized_error(result):
    message = result.stderr.decode(errors='replace')
    return {'exit': result.returncode, 'http': re.findall(r'HTTP (\d+)', message),
            'hosts': sorted(set(re.findall(r'https?://([^/\s?]+)', message))), 'forbidden': 'Forbidden' in message}


def fetch(endpoint, label):
    result = subprocess.run(['gh', 'api', API + endpoint], capture_output=True, timeout=45)
    if result.returncode: raise RuntimeError(json.dumps({'request': label, 'error': sanitized_error(result)}))
    require(0 < len(result.stdout) <= 4 * CHUNK, 'Metadata response is outside its bound.')
    write(SNAPSHOT / (label + '.json'), result.stdout)
    write(ROOT / ('binary-gate-' + label + '.json'), result.stdout, replace=True)
    return parse_json(result.stdout)


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def artifact_identity(artifact, runner, job):
    require(type(artifact.get('id')) is int and artifact['id'] > 0
            and type(artifact.get('size_in_bytes')) is int and 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE
            and artifact.get('expired') is False
            and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SHA
            and artifact['workflow_run']['head_repository_id'] == REPO_ID
            and isinstance(artifact.get('digest'), str) and re.fullmatch('sha256:[0-9a-f]{64}', artifact['digest']),
            'Artifact origin, size, expiry or digest differs.')
    require(timestamp(job['started_at']) <= timestamp(artifact['created_at']) <= timestamp(job['completed_at']) + 5,
            'Artifact creation falls outside its completed native job interval.')


def source_modules():
    # All imported project validators come from the exact configured source,
    # never from the mutable worktree or downloaded artifact payloads.
    paths = ('diagnostics/delivery_archives.py', 'diagnostics/portable_compatibility.py')
    directory = ROOT / 'validator-source'; folder(directory); records = []
    for source in paths:
        result = subprocess.run(['git', 'show', SHA + ':' + source], cwd=REPO, capture_output=True,
                                check=True, timeout=30, env=dict(os.environ, GIT_NO_LAZY_FETCH='1'))
        require(0 < len(result.stdout) < 256 * 1024, 'Pinned validator has an unexpected size.')
        destination = directory / Path(source).name
        if destination.exists(): require(read_regular(destination, 256 * 1024) == result.stdout, 'Pinned validator changed.')
        else: write(destination, result.stdout)
        records.append({'path': source, 'sourceSHA': SHA, 'sha256': hashlib.sha256(result.stdout).hexdigest()})
    write(ROOT / 'collector-binary-validators.json', encode(records), replace=True)
    sys.path.insert(0, str(directory))
    import delivery_archives
    import portable_compatibility
    require(Path(delivery_archives.__file__).resolve() == (directory / 'delivery_archives.py').resolve()
            and Path(portable_compatibility.__file__).resolve() == (directory / 'portable_compatibility.py').resolve(),
            'A different project validator was already imported.')
    return delivery_archives, portable_compatibility, records


def cached_source(runner, artifacts, jobs, small, archives):
    selected = [item for item in artifacts if item['name'] in
                ('PDF-source-' + runner, 'PDF-source-ocr-compatibility-' + runner)]
    require(len(selected) == 1, 'Exactly one approved cached source artifact per runner is required.')
    item = selected[0]; artifact_identity(item, runner, jobs[runner]); ident = str(item['id'])
    record = small['attempts'].get(ident)
    require(isinstance(record, dict) and record.get('downloaded') is True and record.get('extractionVerified') is True
            and record.get('sourceArchiveChecksumVerified') is True and record.get('inventoryComplete') is True
            and (record['runID'], record['sourceSHA'], record['runAttempt'], record['jobID'], record['name'], record['archiveBytes'], record['githubDigest']) ==
                (RUN, SHA, ATTEMPT, JOB_IDS[runner], item['name'], item['size_in_bytes'], item['digest']),
            'Run the small collector first; authenticated complete source evidence is required.')
    archive = ROOT / 'downloads' / (ident + '.zip')
    require(hash_regular(archive, 192 * CHUNK) == {'bytes': item['size_in_bytes'], 'sha256': item['digest'][7:]},
            'Cached source ZIP differs from authenticated GitHub metadata.')
    directory = ROOT / 'extracted' / item['name']
    require(directory.is_dir() and not directory.is_symlink(), 'Cached source directory is invalid.')
    required = {'PDF-source.tar.gz': archives.MAX_SOURCE, 'PDF-source.tar.gz.sha256': 256}
    stream, before = open_regular(archive, 192 * CHUNK)
    with stream:
        files = record['files']; require(len(files) in (2, 3, 4, 5), 'Unexpected cached source file count.')
        archives._zip_directory(stream, before.st_size, len(files))
        with zipfile.ZipFile(stream) as payload:
            entries = payload.infolist(); by_name = {entry.filename: entry for entry in entries}
            require(len(entries) == len(by_name) == len(files) and set(by_name) == {file['name'] for file in files}
                    and set(required) <= set(by_name), 'Cached source ZIP inventory differs.')
            for name, cap in required.items():
                entry = by_name[name]
                require(entry.is_dir() is False and 0 < entry.file_size <= cap and not entry.flag_bits & 1
                        and (entry.external_attr >> 16) & 0o170000 in (0, stat.S_IFREG), 'Invalid cached source member.')
                with payload.open(entry) as content: measured = hash_stream(content, entry.file_size)
                require(hash_regular(directory / name, cap) == measured, 'Cached source bytes differ from original ZIP.')
        unchanged(stream, before)
    return directory, {'id': item['id'], 'name': item['name'], 'githubDigest': item['digest'], 'archiveBytes': item['size_in_bytes']}


class HashedReader:
    """Hash/count exactly the compressed TAR member while its gzip is consumed."""
    def __init__(self, stream, limit):
        self.stream = stream; self.limit = limit; self.count = 0; self.hash = hashlib.sha256()
    def read(self, size=-1):
        require(size <= CHUNK, 'Unbounded compressed TAR read requested.')
        if size < 0: size = CHUNK
        block = self.stream.read(size); self.count += len(block)
        require(self.count <= self.limit, 'Compressed TAR exceeded its authenticated member size.')
        self.hash.update(block); return block


class ExpandedReader:
    """Bound gzip expansion and retain recent read-ahead for exact zero padding."""
    def __init__(self, stream, limit):
        self.stream = stream; self.limit = limit; self.count = 0; self.tail = b''
    def read(self, size=-1):
        require(0 <= size <= CHUNK, 'Unbounded decompressed TAR read requested.')
        block = self.stream.read(size); self.count += len(block)
        require(self.count <= self.limit, 'Expanded TAR exceeds its bound.')
        self.tail = (self.tail + block)[-CHUNK:]
        return block


def contained_links(nodes, links):
    # Resolve the complete archive graph without extracting or following local
    # filesystem links. Every declared link must terminate inside this inventory.
    for name, target in links.items():
        require(target and not target.startswith('/') and '\\' not in target and '\x00' not in target,
                'Absolute or malformed distribution link.')
        current = name; visited = set(); pending_target = target
        for _ in range(64):
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(current), pending_target))
            require(relative != '..' and not relative.startswith('../') and not relative.startswith('/'), 'Link escapes distribution.')
            parts = [] if relative in ('', '.') else relative.split('/'); replaced = False
            for index in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:index])
                if prefix in links:
                    require(prefix not in visited, 'Cyclic distribution link.')
                    visited.add(prefix); current = prefix
                    pending_target = posixpath.join(links[prefix], *parts[index:])
                    replaced = True; break
                require(prefix in nodes and (index == len(parts) or nodes[prefix] == 'directory'), 'Link target is absent or not a directory.')
            if not replaced: break
        else: raise ValueError('Distribution symlink chain exceeds its bound.')


def inspect_tar(payload, entry, manifest, archives):
    require(isinstance(manifest, dict) and type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 1
            and manifest.get('architecture') == 'arm64' and manifest.get('commit') == SHA
            and isinstance(manifest.get('files'), dict) and 0 < len(manifest['files']) <= 200000,
            'Distribution manifest identity differs.')
    for name, value in manifest['files'].items():
        archives._name(name)
        require(isinstance(value, dict), 'Manifest entry must be an object.')
        if value.get('type') == 'file':
            require(set(value) == {'type', 'size', 'mode', 'sha256'} and type(value['size']) is int
                    and 0 <= value['size'] <= MAX_ARCHIVE and type(value['mode']) is int and 0 <= value['mode'] <= 0o7777
                    and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']),
                    'Manifest file record is malformed.')
        else:
            require(set(value) == {'type', 'target'} and value.get('type') == 'symlink'
                    and isinstance(value.get('target'), str) and value['target'], 'Manifest symlink record is malformed.')
    actual = {}; normalized = set(); nodes = {}; links = {}; internal = []; last_end = 0; count = 0
    storage = dict(schemaVersion=1, distributionBytes=0, bundleBytes=0, distributionEntries=0, bundleEntries=0)
    with payload.open(entry) as raw:
        hashed = HashedReader(raw, entry.file_size)
        with gzip.GzipFile(fileobj=hashed, mode='rb') as compressed:
            expanded = ExpandedReader(compressed, MAX_ARCHIVE + 256 * CHUNK)
            with tarfile.open(fileobj=expanded, mode='r|') as tar:
                for item in tar:
                    count += 1
                    require(count <= 250000 and item.sparse is None and not any(key.startswith('GNU.sparse') for key in item.pax_headers)
                            and 0 <= item.size <= MAX_ARCHIVE, 'TAR member count/type/size is invalid.')
                    canonical = archives._name(item.name)
                    require(canonical not in normalized, 'Duplicate or case/Unicode-ambiguous TAR member.')
                    normalized.add(canonical)
                    if item.name == 'PDF-distribution':
                        require(item.isdir(), 'Distribution root must be a directory.')
                        relative = ''
                    else:
                        require(item.name.startswith('PDF-distribution/'), 'Foreign TAR member.')
                        relative = item.name[len('PDF-distribution/'):]
                    last_end = item.offset_data + ((item.size + 511) // 512) * 512
                    if relative == 'manifest.json':
                        require(item.isfile() and 0 < item.size <= archives.MAX_FILE, 'Invalid internal manifest.')
                        with tar.extractfile(item) as content: data = content.read(archives.MAX_FILE + 1)
                        require(len(data) == item.size, 'Truncated internal manifest.')
                        internal.append(parse_json(data)); nodes[relative] = 'file'; continue
                    storage['distributionEntries'] += 1
                    bundled = relative == 'PDF.app' or relative.startswith('PDF.app/')
                    if bundled: storage['bundleEntries'] += 1
                    if item.isdir(): nodes[relative] = 'directory'; continue
                    require(relative, 'Root is not a directory.')
                    if item.issym():
                        require(item.size == 0, 'Symlink has an unexpected data payload.')
                        nodes[relative] = 'symlink'; links[relative] = item.linkname
                        actual[relative] = {'type': 'symlink', 'target': item.linkname}
                    elif item.isfile():
                        nodes[relative] = 'file'
                        storage['distributionBytes'] += item.size
                        if bundled: storage['bundleBytes'] += item.size
                        require(storage['distributionBytes'] <= MAX_ARCHIVE, 'Expanded file payload exceeds12GiB.')
                        with tar.extractfile(item) as content: measured = hash_stream(content, item.size)
                        actual[relative] = {'type': 'file', 'size': measured['bytes'], 'mode': stat.S_IMODE(item.mode), 'sha256': measured['sha256']}
                    else: raise ValueError('Hardlinks and special TAR members are refused.')
            require(last_end <= expanded.count and expanded.count - last_end <= len(expanded.tail), 'TAR trailer cannot be inspected within bounded read-ahead.')
            tail = expanded.tail[len(expanded.tail) - (expanded.count - last_end):] if expanded.count > last_end else b''
            require(not tail.strip(b'\0'), 'TAR contains data outside the declared inventory.')
            padding = len(tail)
            for block in iter(lambda: expanded.read(CHUNK), b''):
                require(not block.strip(b'\0'), 'TAR contains trailing data or another archive.')
                padding += len(block)
            require(padding >= 1024, 'TAR end padding is incomplete.')
        # Gzip must have consumed and validated every compressed byte, including
        # its checksum/trailer. Draining also makes ZipFile validate member CRC.
        require(not hashed.read(CHUNK) and hashed.count == entry.file_size, 'Unconsumed compressed member data.')
    require(internal == [manifest], 'Published manifest differs from the sole internal manifest.')
    require(actual == manifest['files'], 'Actual streamed files differ from the full published manifest.')
    for relative in nodes:
        if relative:
            parent = posixpath.dirname(relative)
            require(parent in nodes and nodes[parent] == 'directory', 'TAR has a missing or non-directory parent.')
    contained_links(nodes, links)
    declared = manifest.get('storageRequirements')
    require(isinstance(declared, dict) and all(type(value) is int for value in declared.values()) and declared == storage,
            'Declared storage does not match streamed files and directory entries.')
    return {'member': entry.filename, 'bytes': hashed.count, 'sha256': hashed.hash.hexdigest(),
            'retainedInsideOriginalZIP': True, 'tarExtracted': False, 'manifestMatchedEveryFile': True,
            'storageRequirementsVerified': storage, 'membersInspected': count, 'expandedBytesInspected': expanded.count}


def validate_binary(archive, artifact, runner, source_dir, archives, portable):
    destination = ROOT / 'extracted' / artifact['name']; folder(destination)
    require({path.name for path in destination.iterdir()} <= set(BINARY_MEMBERS) - {'PDF-arm64.tar.gz'},
            'Binary metadata directory contains unexpected files, including an extracted large TAR.')
    stream, before = open_regular(archive, MAX_ARCHIVE)
    with stream:
        archives._zip_directory(stream, before.st_size, 5)
        with zipfile.ZipFile(stream) as payload:
            entries = payload.infolist(); lookup = {item.filename: item for item in entries}
            require(len(entries) == len(lookup) == 5 and set(lookup) == set(BINARY_MEMBERS), 'Binary ZIP must have exactly the original five members.')
            for item in entries:
                require(not item.is_dir() and not item.flag_bits & 1 and item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        and (item.external_attr >> 16) & 0o170000 in (0, stat.S_IFREG)
                        and 0 < item.file_size <= BINARY_MEMBERS[item.filename], 'Binary ZIP member type/size/filter is invalid.')
            files = []; raw_files = {}
            for name in sorted(set(BINARY_MEMBERS) - {'PDF-arm64.tar.gz'}):
                data = payload.read(lookup[name]); require(len(data) == lookup[name].file_size, 'Truncated binary metadata.')
                target = destination / name
                if target.exists(): require(read_regular(target, BINARY_MEMBERS[name]) == data, 'Existing binary metadata differs from original ZIP.')
                else: write(target, data)
                raw_files[name] = data
                files.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            manifest = parse_json(raw_files['distribution-manifest.json'])
            tar = inspect_tar(payload, lookup['PDF-arm64.tar.gz'], manifest, archives)
        unchanged(stream, before)
    require(raw_files['PDF-arm64.tar.gz.sha256'] == (tar['sha256'] + '  PDF-arm64.tar.gz\n').encode(), 'Tar hash differs from published checksum.')
    validation = parse_json(raw_files['distribution-validation.json'])
    require(isinstance(validation, dict) and type(validation.get('schemaVersion')) is int and validation['schemaVersion'] == 1
            and validation.get('commit') == SHA and validation.get('runner') == runner,
            'Binary validation report identity differs.')
    for key in portable.REQUIRED_CHECKS: require(validation.get(key) is True, 'Missing mandatory binary check: ' + key)
    require(validation.get('developerToolsOnDestinationRequired') is False and validation.get('appleNotarized') is False
            and validation.get('signing') == 'ad-hoc' and type(validation.get('manifestEntries')) is int
            and validation['manifestEntries'] == len(manifest['files']), 'Binary validation claims contradict the manifest.')
    source = archives.verify_source_and_installer(source_dir, destination, SHA, manifest,
        required_source_files=('diagnostics/delivery_archives.py', 'diagnostics/portable_compatibility.py', 'scripts/PDF-Info.plist', 'scripts/check_window_lifecycle.py'))
    for source_path, measured in source['additionalSourceFiles'].items():
        exact_source = subprocess.run(['git', 'show', SHA + ':' + source_path], cwd=REPO, capture_output=True,
                                     check=True, timeout=30, env=dict(os.environ, GIT_NO_LAZY_FETCH='1')).stdout
        require(measured == {'bytes': len(exact_source), 'sha256': hashlib.sha256(exact_source).hexdigest()},
                'Archived validation/production metadata differs from exact git source: ' + source_path)
    exact = subprocess.run(['git', 'show', SHA + ':scripts/install-binary.sh'], cwd=REPO, capture_output=True,
                           check=True, timeout=30, env=dict(os.environ, GIT_NO_LAZY_FETCH='1')).stdout
    require(exact == raw_files['install-binary.sh'], 'Installer differs from exact git source.')
    return dict(tar=tar, files=files, sourceInstaller=source, manifestSHA256=portable.manifest_digest(manifest),
                manifestEntries=len(manifest['files']), validationReportVerified=True, directory=str(destination),
                fullRunApprovalNotInferredFromArtifactName=True, completeApplicationApproved=False)


def main():
    global ROOT, SNAPSHOT, SHA, RUN, ATTEMPT, JOB_IDS
    configured = load_configuration()  # No fallback, request or validator import precedes this check.
    ROOT = Path(configured['outputDirectory']); SHA = configured['sourceCommit']; RUN = configured['nativeRunID']
    ATTEMPT = configured['runAttempt']; JOB_IDS = configured['jobIDs']
    require(ROOT.is_dir() and not ROOT.is_symlink(), 'Run the small collector first in the same dedicated output directory.')
    folder(ROOT)
    require(parse_json(read_regular(ROOT / 'collector-configuration.json', 16384)) == configured,
            'Small/binary collector evidence configurations differ.')
    small = parse_json(read_regular(ROOT / 'collector-artifact-state.json', 4 * CHUNK))
    require((small['runID'], small['sourceSHA'], small['runAttempt']) == (RUN, SHA, ATTEMPT), 'Small collector state belongs to another run.')
    for name in ('downloads', 'extracted', 'binary-snapshots'): folder(ROOT / name)
    SNAPSHOT = ROOT / 'binary-snapshots' / (str(time.time_ns()) + '-' + str(os.getpid())); folder(SNAPSHOT)
    run = fetch(f'/actions/runs/{RUN}', 'run')
    require(run['id'] == RUN and run['head_sha'] == SHA and run['head_commit']['id'] == SHA and run['run_attempt'] == ATTEMPT
            and run['repository']['id'] == REPO_ID and run['head_repository']['id'] == REPO_ID
            and run['path'] == '.github/workflows/macos.yml' and run['status'] == 'completed' and run['conclusion'] == 'success',
            'The complete exact source run must be successful before any binary ZIP download.')
    jobs_response = fetch(f'/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100', 'jobs')
    require(jobs_response['total_count'] == 2 and len(jobs_response['jobs']) == 2, 'Exactly two successful native jobs required.')
    jobs = {}
    for runner, ident in JOB_IDS.items():
        matching = [job for job in jobs_response['jobs'] if job['id'] == ident]
        require(len(matching) == 1, 'Explicit native job ID missing.')
        job = matching[0]
        require(job['run_id'] == RUN and job['head_sha'] == SHA and job['run_attempt'] == ATTEMPT
                and job['name'] == 'native-application (' + runner + ')' and runner in job['labels']
                and job['status'] == 'completed' and job['conclusion'] == 'success', 'A native job is unapproved or has different identity.')
        jobs[runner] = job
    metadata = fetch(f'/actions/runs/{RUN}/artifacts?per_page=100', 'artifacts')
    require(type(metadata['total_count']) is int and 0 < metadata['total_count'] <= 100
            and len(metadata['artifacts']) == metadata['total_count'], 'Artifact pagination is incomplete.')
    artifacts = metadata['artifacts']
    require(len({item['id'] for item in artifacts}) == len(artifacts)
            and len({item['name'] for item in artifacts}) == len(artifacts), 'Artifact IDs/names are ambiguous.')
    selected = {}
    for runner in JOB_IDS:
        matches = [item for item in artifacts if item['name'] == 'PDF-binary-validated-' + runner]
        require(len(matches) == 1, 'Exactly one approved binary artifact per runner required.')
        artifact_identity(matches[0], runner, jobs[runner]); selected[runner] = matches[0]
    require(not any(item['name'].startswith('PDF-binary-unvalidated-') for item in artifacts), 'Run published an unvalidated binary artifact.')
    require(not small.get('proxyBlocked') and not any(not record.get('downloaded') and
            set(record.get('downloadError', {}).get('http', [])) & {'401', '403'} for record in small['attempts'].values()),
            'An unresolved authenticated download refusal requires coordination before binary downloads.')
    archives, portable, validators = source_modules()
    sources = {runner: cached_source(runner, artifacts, jobs, small, archives) for runner in JOB_IDS}
    state_path = ROOT / 'collector-binary-downloads.json'
    state = parse_json(read_regular(state_path, 8 * CHUNK)) if state_path.exists() else dict(schemaVersion=1, configuration=configured, attempts={})
    require(state.get('schemaVersion') == 1 and state.get('configuration') == configured and isinstance(state.get('attempts'), dict), 'Binary collector state belongs to another configuration.')
    def persist(): write(state_path, encode(state), replace=True)
    for runner, item in selected.items():
        ident = str(item['id']); size = item['size_in_bytes']; digest = item['digest'][7:]
        record = state['attempts'].setdefault(ident, dict(id=item['id'], name=item['name'], sourceSHA=SHA, runID=RUN,
                runAttempt=ATTEMPT, jobID=JOB_IDS[runner], archiveBytes=size, githubDigest=item['digest'], downloadAttempts=0))
        require((record['name'], record['sourceSHA'], record['runID'], record['runAttempt'], record['jobID'], record['archiveBytes'], record['githubDigest']) ==
                (item['name'], SHA, RUN, ATTEMPT, JOB_IDS[runner], size, item['digest']), 'Existing binary artifact identity changed.')
        archive = ROOT / 'downloads' / (ident + '.zip')
        if archive.exists():
            require(hash_regular(archive) == {'bytes': size, 'sha256': digest}, 'Cached binary ZIP changed; no redownload attempted.')
        else:
            require(record['downloadAttempts'] < 3, 'Binary download retry limit reached.')
            require(shutil.disk_usage(ROOT).free >= size + 256 * CHUNK, 'Insufficient space for original ZIP plus metadata margin; no TAR expansion is attempted.')
            record['downloadAttempts'] += 1; record['attemptedAt'] = time.time(); persist()
            temporary = archive.with_suffix('.zip.partial')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            identity = os.fstat(descriptor)
            try:
                def bound(): resource.setrlimit(resource.RLIMIT_FSIZE, (size + 1024, size + 1024))
                with os.fdopen(descriptor, 'wb') as output:
                    try:
                        result = subprocess.run(['gh', 'api', API + f'/actions/artifacts/{ident}/zip'], stdout=output,
                                                stderr=subprocess.PIPE, timeout=600, preexec_fn=bound)
                    except subprocess.TimeoutExpired:
                        record['downloadError'] = {'timeoutSeconds': 600}; persist(); raise
                if result.returncode:
                    record['downloadError'] = sanitized_error(result); persist()
                    raise RuntimeError(json.dumps({'artifact': item['name'], 'downloadError': record['downloadError']}))
                require(hash_regular(temporary) == {'bytes': size, 'sha256': digest}, 'Downloaded ZIP differs from authenticated digest/size.')
                # Publish without replacing a concurrently created original.
                os.link(temporary, archive, follow_symlinks=False); temporary.unlink()
            finally:
                if os.path.lexists(temporary):
                    current = temporary.lstat()
                    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino): temporary.unlink()
        record.update(downloaded=True, archiveSHA256=digest); record.pop('downloadError', None); persist()
        try:
            record.update(validate_binary(archive, item, runner, sources[runner][0], archives, portable))
            record.update(sourceArtifact=sources[runner][1], validationVerifiedAt=time.time())
            record.pop('validationError', None)
        except Exception as exception:
            record['validationError'] = {'type': type(exception).__name__, 'message': str(exception)[:1024]}; persist(); raise
        persist(); print(json.dumps(record), flush=True)
    require({record['name'] for record in state['attempts'].values() if record.get('downloaded') and record.get('validationReportVerified')
             and not record.get('validationError')} == {item['name'] for item in selected.values()}, 'Both complete verified binary records are required.')
    summary = dict(sourceSHA=SHA, runID=RUN, runAttempt=ATTEMPT, jobs=JOB_IDS, binaryArtifacts=2,
                   exactRunAndBothJobsPassed=True, binaryTarsExtracted=False, completeApplicationApproved=False,
                   sourceValidators=validators, snapshotDirectory=str(SNAPSHOT))
    write(ROOT / 'collector-binary-summary.json', encode(summary), replace=True); print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
