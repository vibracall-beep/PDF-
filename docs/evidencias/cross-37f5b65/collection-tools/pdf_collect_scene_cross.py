#!/usr/bin/env python3
"""Collect exact cross-run originals; no publication, binary download or rebuild.

Prepared for root review. Every network action is behind an explicit complete
configuration; incomplete and failed cross runs are retained without approval.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import re
import resource
import stat
import struct
import subprocess
import sys
import tarfile
import time
import zipfile

CONFIG = Path('/tmp/pdf-scene-cross.json')
REPO = Path('/workspace/PDF-')
REPOSITORY = 'vibracall-beep/PDF-'
REPOSITORY_ID = 1431437116
API = '/repos/' + REPOSITORY
ROOT = SNAPSHOT = None
MAX_BINARY = 12 * 1024**3
CONTROLLER_FILES = (
    'diagnostics/deliver_binary.py', 'diagnostics/delivery_archives.py',
    'diagnostics/cross_gui_evidence.py', 'diagnostics/portable_compatibility.py',
    'diagnostics/retain_evidence.py', 'diagnostics/delivery_lifecycle.py',
    'diagnostics/delivery_parts.py',
    'scripts/check_preview_artifacts.py', 'scripts/check_accessibility_report.py',
    'scripts/check_window_lifecycle.py', 'scripts/PDF-Info.plist',
)

def require(condition, detail):
    if not condition: raise ValueError(detail)

def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result

def invalid_constant(value):
    raise ValueError('Non-finite JSON value is not accepted: ' + value)

def parse_json(raw):
    return json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_constant)

def read_regular(path, limit, *, allow_empty=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and (0 if allow_empty else 1) <= before.st_size <= limit,
                'Expected bounded, owned regular file: ' + path.name)
        raw = stream.read(limit + 1); after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, len(raw), after.st_mtime_ns, after.st_ctime_ns),
                'File changed while reading: ' + path.name)
        return raw

def folder(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077, 'Evidence directory is not private/owned.')

def write(path, data, replace=False):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if replace:
        temp = path.with_name(path.name + '.pending-' + str(os.getpid()))
        with os.fdopen(os.open(temp, flags, 0o600), 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        if os.path.lexists(path):
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), 'Unexpected existing evidence file.')
        os.replace(temp, path)
    else:
        with os.fdopen(os.open(path, flags, 0o600), 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())

def encode(value): return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()

def error(result):
    message = result.stderr.decode(errors='replace')
    return {'exit': result.returncode, 'http': re.findall(r'HTTP (\d+)', message),
            'hosts': sorted(set(re.findall(r'https?://([^/\s?]+)', message))),
            'forbidden': 'Forbidden' in message}

def timestamp(value): return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()

def fetch(endpoint, label):
    result = subprocess.run(['gh', 'api', API + endpoint], capture_output=True, timeout=45)
    if result.returncode: raise RuntimeError(json.dumps({'request': label, 'error': error(result)}))
    require(len(result.stdout) <= 4 * 1024**2, 'Metadata response exceeds limit.')
    write(SNAPSHOT / (label + '.json'), result.stdout)
    write(SNAPSHOT / (label + '-record.json'), encode({
        'endpoint': API + endpoint, 'bytes': len(result.stdout),
        'sha256': hashlib.sha256(result.stdout).hexdigest(), 'authenticatedAPIResponse': True,
    }))
    write(ROOT / ('collector-' + label + '.json'), result.stdout, replace=True)
    return parse_json(result.stdout)

def configuration():
    raw = read_regular(CONFIG, 16384); value = parse_json(raw)
    fields = {'schemaVersion', 'sourceCommit', 'nativeRunID', 'nativeAttempt', 'nativeRoot',
              'archiveSHA256', 'crossRunID', 'crossAttempt', 'controlCommit', 'crossJobID', 'outputDirectory'}
    require(isinstance(value, dict) and set(value) == fields, 'Complete explicit cross configuration required before GETs.')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1, 'Unsupported collector configuration.')
    for field in ('sourceCommit', 'controlCommit'):
        require(isinstance(value[field], str) and re.fullmatch('[0-9a-f]{40}', value[field]), 'Exact commit required: ' + field)
    require(isinstance(value['archiveSHA256'], str) and re.fullmatch('[0-9a-f]{64}', value['archiveSHA256']),
            'Independent complete tar SHA-256 required before GETs.')
    for field in ('nativeRunID', 'nativeAttempt', 'crossRunID', 'crossAttempt', 'crossJobID'):
        require(type(value[field]) is int and 0 < value[field] < 2**63, 'Positive explicit ID/attempt required: ' + field)
    require(value['nativeRunID'] != value['crossRunID'], 'Native and cross runs must differ.')
    suffix = value['sourceCommit'][:7]
    require(value['nativeRoot'] in {'/workspace/.cache/pdf-native-' + suffix, '/tmp/pdf-native-' + suffix},
            'The authenticated native-root path must match the source commit.')
    native = Path(value['nativeRoot'])
    require(native.is_dir() and not native.is_symlink() and native.resolve() == native,
            'Native evidence root must already exist as a real directory.')
    require(native.stat().st_uid == os.getuid() and not native.stat().st_mode & 0o077,
            'Native evidence root must be private and owned by the collector user.')
    target = '/workspace/.cache/pdf-cross-' + suffix
    require(value['outputDirectory'] in {target, target + '/run-' + str(value['crossRunID'])},
            'Cross evidence must have its dedicated source/run directory.')
    return value, raw


def identity(path):
    value = path.lstat()
    require(stat.S_ISREG(value.st_mode) and value.st_uid == os.getuid(), 'Original archive must remain a regular owned file.')
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def hash_regular(path, limit):
    original = identity(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and 0 < before.st_size <= limit,
                'Expected owned bounded archive: ' + path.name)
        digest = hashlib.sha256(); count = 0
        for block in iter(lambda: stream.read(1024**2), b''):
            count += len(block); require(count <= limit, 'Archive grew beyond its bound.'); digest.update(block)
        after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, count, after.st_mtime_ns, after.st_ctime_ns), 'Archive changed while hashing.')
        require(original == identity(path) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                'Original archive path changed during hashing.')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def pin(commit, paths, destination):
    folder(destination); records = {}
    for relative in paths:
        require(relative.count('/') == 1 and relative.split('/')[0] in ('diagnostics', 'scripts'), 'Unexpected validator path.')
        result = subprocess.run(['git', 'show', commit + ':' + relative], cwd=REPO, capture_output=True,
                                timeout=30, env=dict(os.environ, GIT_NO_LAZY_FETCH='1'))
        require(result.returncode == 0 and 0 < len(result.stdout) <= 2 * 1024**2,
                'Exact local validator/source object unavailable: ' + relative)
        target = destination / relative; folder(target.parent)
        if target.exists(): require(read_regular(target, 2 * 1024**2) == result.stdout, 'A pinned validator changed.')
        else: write(target, result.stdout)
        records[relative] = {'bytes': len(result.stdout), 'sha256': hashlib.sha256(result.stdout).hexdigest()}
    return records


def zip_members(path, allowed, total_limit, archives):
    before = identity(path)
    measured = hash_regular(path, total_limit + 32 * 1024**2 + 65557)
    with path.open('rb') as stream:
        length = min(measured['bytes'], 65557); stream.seek(measured['bytes'] - length); tail = stream.read(length)
        offset = tail.rfind(b'PK\x05\x06')
        require(offset >= 0 and offset + 22 <= len(tail), 'Missing bounded ZIP end record.')
        end = struct.unpack('<4s4H2IH', tail[offset:offset+22]); count = end[4]
        if count == 65535:
            absolute = measured['bytes'] - length + offset
            require(absolute >= 20, 'Missing ZIP64 locator.')
            stream.seek(absolute-20); locator = struct.unpack('<4sIQI', stream.read(20))
            require(locator[0] == b'PK\x06\x07' and locator[2] + 56 <= absolute-20, 'Invalid ZIP64 locator.')
            stream.seek(locator[2]); record = struct.unpack('<4sQ2H2I4Q', stream.read(56)); count = record[7]
        require(0 < count <= len(allowed), 'Unexpected ZIP member count.')
        archives._zip_directory(stream, measured['bytes'], count)
        with zipfile.ZipFile(stream) as z:
            entries = z.infolist()
            require(len(entries) == count and len({e.filename for e in entries}) == count
                    and all(e.filename in allowed and not e.is_dir() and not e.flag_bits & 1
                            and (e.external_attr >> 16) & 0o170000 in (0, 0o100000)
                            and (0 if e.filename.endswith('.log') else 1) <= e.file_size <= allowed[e.filename]
                            for e in entries), 'Unexpected/duplicate/unsafe ZIP member or size.')
            require(sum(e.file_size for e in entries) <= total_limit, 'ZIP expanded total exceeds its bound.')
            require(identity(path) == before, 'Original ZIP changed during inventory validation.')
            return {e.filename: allowed[e.filename] for e in entries}


def extract_originals(archive, destination, allowed, total_limit, archives, *, complete):
    before = identity(archive)
    present = zip_members(archive, allowed, total_limit, archives)
    if complete: require(set(present) == set(allowed), 'Required complete artifact inventory is absent.')
    if not destination.exists():
        files = archives.extract_zip(archive, destination, present, total_limit=total_limit)
        require(identity(archive) == before, 'Original ZIP changed during extraction.')
        return files
    require(destination.is_dir() and not destination.is_symlink()
            and {p.name for p in destination.iterdir()} == set(present), 'Existing extraction differs; preserve for review.')
    files = {}
    with zipfile.ZipFile(archive) as z:
        for name, cap in present.items():
            original = z.read(name); actual = read_regular(destination/name, cap, allow_empty=name.endswith('.log'))
            require(actual == original, 'An extracted original changed: ' + name)
            files[name] = destination/name
    require(identity(archive) == before, 'Original ZIP changed while comparing retained files.')
    return files


def download(route, target, limit, *, expected=None):
    if target.exists():
        result = hash_regular(target, limit)
        require(expected is None or result == expected, 'Cached archive differs from authenticated metadata.')
        return result
    temporary = target.with_suffix(target.suffix + '.partial')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        def bounded(): resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
        with os.fdopen(descriptor, 'wb') as output:
            result = subprocess.run(['gh', 'api', API + route], stdout=output, stderr=subprocess.PIPE,
                                    timeout=180, preexec_fn=bounded)
        require(result.returncode == 0, 'Authenticated download failed: ' + json.dumps(error(result)))
        measured = hash_regular(temporary, limit)
        require(expected is None or measured == expected, 'Downloaded digest/size differs from authenticated metadata.')
        temporary.rename(target)
        return measured
    finally:
        if temporary.exists(): temporary.unlink()


class TarHashReader:
    def __init__(self, stream, maximum):
        self.stream = stream; self.maximum = maximum; self.count = 0; self.digest = hashlib.sha256()
    def read(self, count=-1):
        maximum = self.maximum - self.count + 1
        data = self.stream.read(min(count, maximum) if count >= 0 else maximum)
        self.count += len(data); require(self.count <= self.maximum, 'Binary tar grew beyond its ZIP size.')
        self.digest.update(data); return data


def native_binary(config, artifact, origin, directory, archives, portable, delivery):
    # Read the already retained original ZIP, never download a binary or write
    # a second multi-GB tar. Stream its tar hash/internal manifest in one pass.
    archive = Path(config['nativeRoot']) / 'downloads' / (str(artifact['id']) + '.zip')
    before = identity(archive)
    authenticated = {'bytes': artifact['size_in_bytes'], 'sha256': artifact['digest'][7:]}
    require(hash_regular(archive, MAX_BINARY) == authenticated, 'Native original binary ZIP is missing/changed.')
    present = zip_members(archive, delivery.BINARY_CONTENTS, MAX_BINARY, archives)
    require(set(present) == set(delivery.BINARY_CONTENTS), 'Native binary ZIP inventory differs.')
    folder(directory); raw = {}; internal = []; count = 0; expanded = 0
    with zipfile.ZipFile(archive) as z:
        tar_info = z.getinfo(portable.ARCHIVE)
        with z.open(tar_info) as compressed:
            reader = TarHashReader(compressed, tar_info.file_size)
            with tarfile.open(fileobj=reader, mode='r|gz') as tar:
                for member in tar:
                    count += 1; expanded += member.size
                    require(count <= 250000 and 0 <= member.size <= MAX_BINARY and expanded <= MAX_BINARY,
                            'Native tar count/expanded size exceeds the bound.')
                    if member.name == 'PDF-distribution/manifest.json':
                        require(member.isfile() and 0 < member.size <= portable.MAX_MANIFEST,
                                'Native internal manifest is not a bounded regular file.')
                        value = tar.extractfile(member).read(portable.MAX_MANIFEST + 1)
                        require(len(value) == member.size, 'Native internal manifest is truncated.')
                        internal.append(parse_json(value))
            while reader.read(1024**2): pass
            require(reader.count == tar_info.file_size and reader.digest.hexdigest() == config['archiveSHA256'],
                    'Native original tar differs from the independently configured SHA-256.')
        for name in present:
            if name == portable.ARCHIVE: continue
            raw[name] = z.read(name)
            target = directory/name
            if target.exists(): require(read_regular(target, present[name]) == raw[name], 'Native small original changed.')
            else: write(target, raw[name])
    require(identity(archive) == before, 'Native original binary ZIP changed while reading its tar.')
    require(raw[portable.ARCHIVE + '.sha256'] == (config['archiveSHA256'] + '  ' + portable.ARCHIVE + '\n').encode(),
            'Native checksum sidecar differs.')
    manifest = parse_json(raw['distribution-manifest.json']); validation = parse_json(raw['distribution-validation.json'])
    require(internal == [manifest] and type(manifest.get('schemaVersion')) is int and manifest['schemaVersion'] == 1
            and manifest.get('architecture') == 'arm64' and manifest.get('commit') == config['sourceCommit']
            and isinstance(manifest.get('files'), dict) and 0 < len(manifest['files']) <= 200000,
            'Native internal/published manifest or source identity differs.')
    require(type(validation.get('schemaVersion')) is int and validation['schemaVersion'] == 1
            and validation.get('commit') == config['sourceCommit'] and validation.get('runner') == 'macos-26'
            and all(validation.get(check) is True for check in portable.REQUIRED_CHECKS)
            and validation.get('developerToolsOnDestinationRequired') is False
            and validation.get('appleNotarized') is False and validation.get('signing') == 'ad-hoc'
            and validation.get('manifestEntries') == len(manifest['files']), 'Native original validation differs.')
    verified = dict(origin, archiveSHA256=config['archiveSHA256'], archiveBytes=tar_info.file_size,
                    archiveManifestMatched=True, sourceValidationMatched=True,
                    manifestSHA256=portable.manifest_digest(manifest), manifestEntries=len(manifest['files']),
                    applicationVersion=validation.get('applicationVersion'))
    return manifest, verified, {'localOriginalZIP': str(archive), **authenticated,
                               'tarStreamedWithoutExtraction': True, 'tarBytes': tar_info.file_size,
                               'tarSHA256': config['archiveSHA256'], 'tarMembers': count, 'tarDeclaredExpandedBytes': expanded}


def main():
    global ROOT, SNAPSHOT
    config, raw_config = configuration()  # Before every GET, validator or download.
    ROOT = Path(config['outputDirectory']); folder(ROOT.parent)
    folder(ROOT)
    binding = ROOT/'collector-configuration.json'
    if binding.exists(): require(parse_json(read_regular(binding, 16384)) == config, 'Evidence directory belongs to another configuration.')
    else: write(binding, raw_config)
    for name in ('snapshots', 'downloads', 'extracted', 'native-inputs'): folder(ROOT/name)
    SNAPSHOT = ROOT/'snapshots'/(str(time.time_ns())+'-'+str(os.getpid())); folder(SNAPSHOT)
    controller = ROOT/'controller-source'
    controller_records = pin(config['controlCommit'], CONTROLLER_FILES, controller)
    write(SNAPSHOT/'controller-files.json', encode(controller_records))
    sys.path[:0] = [str(controller/'diagnostics'), str(controller/'scripts')]
    import deliver_binary as delivery
    import delivery_archives as archives
    import cross_gui_evidence as gui
    import delivery_lifecycle as lifecycle
    import portable_compatibility as portable
    for name in ('deliver_binary', 'delivery_archives', 'cross_gui_evidence', 'delivery_lifecycle',
                 'portable_compatibility', 'retain_evidence', 'delivery_parts'):
        require(Path(sys.modules[name].__file__).resolve() == controller/'diagnostics'/(name+'.py'),
                'A validator was loaded from another checkout.')
    require(len(delivery.CROSS_CONTENTS) == 50 and len(gui.PNG_NAMES) == 33 and len(gui.AX_NAMES) == 7
            and len(gui.ORIGINALS) == 42 and set(lifecycle.contents(True)) == {'cross.json', 'cross-receipt.json', 'cross.log'},
            'Cross preview/lifecycle inventory contract changed.')
    required_source_files = tuple(dict.fromkeys(tuple('scripts/'+name for name in gui.SCRIPT_NAMES)
                                               + lifecycle.REQUIRED_SOURCE_FILES))
    source_records = pin(config['sourceCommit'], required_source_files, ROOT/'application-source')
    write(SNAPSHOT/'application-files.json', encode(source_records))

    native_run = fetch('/actions/runs/'+str(config['nativeRunID']), 'native-run')
    native_jobs_response = fetch('/actions/runs/'+str(config['nativeRunID'])+'/attempts/'+str(config['nativeAttempt'])+'/jobs?per_page=100', 'native-jobs')
    native_artifacts_response = fetch('/actions/runs/'+str(config['nativeRunID'])+'/artifacts?per_page=100', 'native-artifacts')
    native_jobs = delivery.inventory(native_jobs_response, 'jobs'); native_artifacts = delivery.inventory(native_artifacts_response, 'artifacts')
    require(native_run['run_attempt'] == config['nativeAttempt'] and native_run['repository']['id'] == REPOSITORY_ID,
            'Native attempt/repository differs from configuration.')
    jobs = delivery.validate_run(native_run, native_jobs, str(config['nativeRunID']), config['sourceCommit'], REPOSITORY,
                                 delivery.SOURCE_WORKFLOW, delivery.SOURCE_JOBS, delivery.SOURCE_STEPS)
    native_job = jobs['native-application (macos-26)']
    binary_artifact = delivery.select_artifact(native_artifacts, (portable.ARTIFACT,), native_run, native_job, MAX_BINARY)
    source_artifact = delivery.select_artifact(native_artifacts, delivery.SOURCE_NAMES, native_run, native_job, 256*1024**2)
    origin = portable.validate_origin(native_run, native_jobs, native_artifacts, str(config['nativeRunID']), config['sourceCommit'], REPOSITORY)
    origin['expectedArchiveSHA256'] = config['archiveSHA256']

    cross_run = fetch('/actions/runs/'+str(config['crossRunID']), 'cross-run')
    cross_jobs_response = fetch('/actions/runs/'+str(config['crossRunID'])+'/attempts/'+str(config['crossAttempt'])+'/jobs?per_page=100', 'cross-jobs')
    cross_artifacts_response = fetch('/actions/runs/'+str(config['crossRunID'])+'/artifacts?per_page=100', 'cross-artifacts')
    cross_jobs = delivery.inventory(cross_jobs_response, 'jobs'); cross_artifacts = delivery.inventory(cross_artifacts_response, 'artifacts')
    require(cross_run['id'] == config['crossRunID'] and cross_run['head_sha'] == config['controlCommit']
            and cross_run['run_attempt'] == config['crossAttempt'] and cross_run['path'] == delivery.CROSS_WORKFLOW
            and cross_run['repository']['id'] == cross_run['head_repository']['id'] == REPOSITORY_ID,
            'Cross run identity differs from configuration.')
    require(len(cross_jobs) == 1, 'Exactly one cross job is required.')
    job = cross_jobs[0]
    require(job['id'] == config['crossJobID'] and job['run_id'] == config['crossRunID']
            and job['run_attempt'] == config['crossAttempt'] and job['head_sha'] == config['controlCommit']
            and job['name'] == 'compatible-binary' and 'xcode-27' in job['labels'], 'Cross job identity differs.')
    cross_success = False; cross_gate_error = None
    try:
        delivery.validate_run(cross_run, cross_jobs, str(config['crossRunID']), config['controlCommit'], REPOSITORY,
                              delivery.CROSS_WORKFLOW, ('compatible-binary',), delivery.CROSS_STEPS)
        cross_success = True
    except ValueError as failure:
        cross_gate_error = str(failure)

    allowed_names = {'PDF-cross-platform-validated', 'PDF-cross-platform-unvalidated', 'PDF-cross-lifecycle'}
    require(len(cross_artifacts) <= 2 and len({a['name'] for a in cross_artifacts}) == len(cross_artifacts)
            and len({a['id'] for a in cross_artifacts}) == len(cross_artifacts)
            and all(a['name'] in allowed_names for a in cross_artifacts), 'Unexpected or duplicate cross artifact.')
    if cross_success:
        require({a['name'] for a in cross_artifacts} == {'PDF-cross-platform-validated', 'PDF-cross-lifecycle'},
                'Successful cross run lacks its two complete separate artifacts.')
    records = []; directories = {}
    for artifact in cross_artifacts:
        name = artifact['name']; life = name == 'PDF-cross-lifecycle'
        allowed = lifecycle.contents(True) if life else delivery.CROSS_CONTENTS
        limit = 80*1024**2 if life else gui.MAX_TOTAL
        require(type(artifact['id']) is int and artifact['id'] > 0 and artifact['expired'] is False
                and type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= limit
                and isinstance(artifact.get('digest'), str) and re.fullmatch('sha256:[0-9a-f]{64}', artifact['digest'])
                and artifact['workflow_run']['id'] == config['crossRunID']
                and artifact['workflow_run']['head_sha'] == config['controlCommit']
                and artifact['workflow_run']['repository_id'] == artifact['workflow_run']['head_repository_id'] == REPOSITORY_ID,
                'Cross artifact origin, expiry, digest or size differs.')
        require(timestamp(artifact['created_at']) >= timestamp(job['started_at'])
                and (job['completed_at'] is None or timestamp(artifact['created_at']) <= timestamp(job['completed_at'])),
                'Cross artifact belongs to another job interval.')
        target = ROOT/'downloads'/(str(artifact['id'])+'.zip')
        measured = download('/actions/artifacts/'+str(artifact['id'])+'/zip', target, limit,
                            expected={'bytes': artifact['size_in_bytes'], 'sha256': artifact['digest'][7:]})
        destination = ROOT/'extracted'/name
        files = extract_originals(target, destination, allowed, limit, archives, complete=cross_success)
        directories[name] = destination
        file_records = {}
        for filename, path in sorted(files.items()):
            original = read_regular(path, allowed[filename], allow_empty=filename.endswith('.log'))
            file_records[filename] = {'bytes':len(original),'sha256':hashlib.sha256(original).hexdigest()}
        records.append({'artifactID':artifact['id'], 'name':name, 'archive':measured, 'githubDigest':artifact['digest'],
                        'runID':config['crossRunID'], 'jobID':job['id'], 'controllerCommit':config['controlCommit'],
                        'sourceCommit':config['sourceCommit'], 'directory':str(destination),
                        'missingRequiredFiles':sorted(set(allowed)-set(files)),
                        'files':file_records,
                        'sourceBinaryAndGUIReceiptVerified':False, 'lifecycleReceiptVerified':False})
        write(ROOT/'collector-artifact-state.json', encode(records), replace=True)

    logs = None
    if cross_run['status'] == 'completed':
        target = ROOT/'downloads'/('run-'+str(config['crossRunID'])+'-attempt-'+str(config['crossAttempt'])+'-logs.zip')
        logs = download('/actions/runs/'+str(config['crossRunID'])+'/attempts/'+str(config['crossAttempt'])+'/logs', target, 64*1024**2)
        # Original authenticated official run-log ZIP, retained without
        # extraction. GitHub does not publish a digest for this endpoint.
        logs.update(path=str(target), authenticatedAPIEndpoint=True, githubDigestProvided=False, extracted=False)
        write(SNAPSHOT/'run-logs-record.json', encode(logs))

    summary = {'schemaVersion':1,'sourceCommit':config['sourceCommit'],'sourceRunID':config['nativeRunID'],
               'crossRunID':config['crossRunID'],'crossAttempt':config['crossAttempt'],'controllerCommit':config['controlCommit'],
               'crossJobID':config['crossJobID'],'archiveSHA256':config['archiveSHA256'],
               'runStatus':cross_run['status'],'runConclusion':cross_run['conclusion'],
               'completeNativeAndCrossGatesPassed':cross_success,'crossGateFailure':cross_gate_error,
               'receiptVerified':False,'lifecycleReceiptVerified':False,'originalRunLogs':logs,
               'noBinaryDownloaded':True,'completeApplicationApproved':False,'humanVisualReview':False,
               'humanVoiceOverTested':False,'snapshotDirectory':str(SNAPSHOT)}
    if cross_success:
        manifest, verified, binary_record = native_binary(config, binary_artifact, origin, ROOT/'native-inputs'/'binary-small', archives, portable, delivery)
        source_zip = Path(config['nativeRoot'])/'downloads'/(str(source_artifact['id'])+'.zip')
        require(hash_regular(source_zip, 256*1024**2) == {'bytes':source_artifact['size_in_bytes'],'sha256':source_artifact['digest'][7:]},
                'Native original source ZIP is missing or changed.')
        source_dir = ROOT/'native-inputs'/'source'
        extract_originals(source_zip, source_dir, delivery.SOURCE_CONTENTS, 256*1024**2, archives, complete=True)
        source_verified = archives.verify_source_and_installer(source_dir, ROOT/'native-inputs'/'binary-small', config['sourceCommit'], manifest,
                                                              required_source_files=required_source_files)
        require(source_verified['additionalSourceFiles'] == source_records,
                'Original source archive validators differ from the exact configured application Git commit.')
        for name in ('scripts/check_preview_artifacts.py', 'scripts/check_accessibility_report.py', 'scripts/check_window_lifecycle.py'):
            require(controller_records[name] == source_records[name], 'Controller validator differs from authenticated application source: '+name)
        platform_dir = directories['PDF-cross-platform-validated']; lifecycle_dir = directories['PDF-cross-lifecycle']
        cross_report = delivery.verify_cross_reports(platform_dir, origin, verified, manifest, source_verified)
        require(all(cross_report.get(key) is False for key in ('physicalM4Measured','neuralEngineMeasured','humanVoiceOverTested')),
                'Cross report claims unsupported hardware or human testing.')
        lifecycle_verified = lifecycle.verify(lifecycle_dir, source_commit=config['sourceCommit'], job=job,
                                               source_verification=source_verified, manifest=manifest)
        for item in records:
            if item['name'] == 'PDF-cross-platform-validated': item['sourceBinaryAndGUIReceiptVerified'] = True
            if item['name'] == 'PDF-cross-lifecycle': item['lifecycleReceiptVerified'] = True
        write(ROOT/'collector-artifact-state.json', encode(records), replace=True)
        write(SNAPSHOT/'native-binary-verification.json', encode(binary_record))
        write(SNAPSHOT/'native-source-verification.json', encode(source_verified))
        write(SNAPSHOT/'cross-lifecycle-verification.json', encode(lifecycle_verified))
        write(SNAPSHOT/'cross-archive-verification.json', encode(verified))
        summary.update(receiptVerified=True,lifecycleReceiptVerified=True,originalPNGCount=33,originalAXCount=7,originalOCRCount=2,
                       crossArtifactFileCount=50,separateLifecycleFiles=3,
                       authenticatedNativeManifestSHA256=verified['manifestSHA256'])
    write(ROOT/'collector-summary.json', encode(summary), replace=True)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if cross_success else 2


if __name__ == '__main__':
    raise SystemExit(main())
