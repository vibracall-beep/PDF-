#!/usr/bin/env python3
"""Collect authenticated small CI artifacts for one exact run; never publish."""
from pathlib import Path
from datetime import datetime
import contextlib
import hashlib
import io
import json
import os
import re
import resource
import stat
import struct
import subprocess
import sys
import time
import zipfile

CONFIG = Path('/tmp/pdf-scene-candidate.json')
REPO = Path('/workspace/PDF-')
REPO_ID = 1431437116
API = '/repos/vibracall-beep/PDF-'
# Assigned only by main(), after every required configuration value is checked.
ROOT = RUN = SHA = ATTEMPT = JOB_IDS = SNAPSHOT = None


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


def load_configuration():
    # This must precede every GET and every validator execution. A missing,
    # incomplete or placeholder configuration never falls back to an old run.
    raw = read_regular(CONFIG, 16384)
    value = parse_json(raw)
    fields = {'schemaVersion', 'sourceCommit', 'nativeRunID', 'runAttempt', 'jobIDs', 'outputDirectory'}
    require(isinstance(value, dict) and set(value) == fields, 'Explicit complete collector configuration required.')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1, 'Unsupported collector configuration.')
    require(isinstance(value['sourceCommit'], str) and re.fullmatch('[0-9a-f]{40}', value['sourceCommit']),
            'Exact 40-character sourceCommit required before network access.')
    for key in ('nativeRunID', 'runAttempt'):
        require(type(value[key]) is int and 0 < value[key] < 2**63, 'Positive integer ' + key + ' required.')
    require(isinstance(value['jobIDs'], dict) and set(value['jobIDs']) == {'macos-26', 'xcode-27'}
            and all(type(number) is int and 0 < number < 2**63 for number in value['jobIDs'].values())
            and len(set(value['jobIDs'].values())) == 2, 'Two distinct explicit native job IDs required.')
    allowed_roots = {'/tmp/pdf-native-scene-candidate',
                     '/workspace/.cache/pdf-native-' + value['sourceCommit'][:7]}
    require(isinstance(value['outputDirectory'], str) and value['outputDirectory'] in allowed_roots,
            'Output must be the dedicated candidate evidence directory, never the previous 81769db evidence.')
    return value, raw


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


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''): result.update(part)
    return result.hexdigest()


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
    write(ROOT / ('collector-' + label + '.json'), result.stdout, replace=True)
    return json.loads(result.stdout)


def main():
    global ROOT, RUN, SHA, ATTEMPT, JOB_IDS, SNAPSHOT
    configured, raw_config = load_configuration()
    ROOT = Path(configured['outputDirectory']); RUN = configured['nativeRunID']
    SHA = configured['sourceCommit']; ATTEMPT = configured['runAttempt']; JOB_IDS = configured['jobIDs']
    folder(ROOT)
    binding = ROOT / 'collector-configuration.json'
    if binding.exists():
        require(parse_json(read_regular(binding, 16384)) == configured, 'Evidence directory belongs to another source/run configuration.')
    else:
        write(binding, raw_config)
    for name in ('snapshots', 'downloads', 'extracted', 'validator-source'): folder(ROOT / name)
    SNAPSHOT = ROOT / 'snapshots' / (str(time.time_ns()) + '-' + str(os.getpid()))
    folder(SNAPSHOT)

    # Execute only validators from the requested commit, not from a later mutable
    # worktree and never from any downloaded artifact.
    validator_records = []
    for source in ('diagnostics/delivery_archives.py', 'scripts/check_preview_artifacts.py',
                   'scripts/check_accessibility_report.py', 'scripts/check_window_lifecycle.py'):
        result = subprocess.run(['git', 'show', SHA + ':' + source], cwd=REPO, capture_output=True, check=True, env=dict(os.environ, GIT_NO_LAZY_FETCH='1'))
        require(0 < len(result.stdout) < 256 * 1024, 'Validator source is unexpectedly large.')
        path = ROOT / 'validator-source' / Path(source).name
        if path.exists(): require(path.read_bytes() == result.stdout, 'Pinned validator changed.')
        else: write(path, result.stdout)
        validator_records.append({'path': source, 'sourceSHA': SHA, 'sha256': hashlib.sha256(result.stdout).hexdigest()})
    write(ROOT / 'collector-validators.json', encode(validator_records), replace=True)
    sys.path.insert(0, str(ROOT / 'validator-source'))
    from delivery_archives import extract_zip, _zip_directory
    from check_preview_artifacts import PREVIEW_STATES, REQUIRED_AX, check_directory
    from check_window_lifecycle import validate as validate_lifecycle_report
    require(len(PREVIEW_STATES) == 33 and len(REQUIRED_AX) == 7, 'Requested preview inventory changed.')

    run = fetch(f'/actions/runs/{RUN}', 'run')
    require(run['id'] == RUN and run['head_sha'] == SHA and run['head_commit']['id'] == SHA
            and run['run_attempt'] == ATTEMPT and run['repository']['id'] == REPO_ID
            and run['head_repository']['id'] == REPO_ID and run['path'] == '.github/workflows/macos.yml',
            'Run identity differs from the requested run/commit/attempt.')
    jobs_response = fetch(f'/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100', 'jobs')
    require(jobs_response['total_count'] == 2 and len(jobs_response['jobs']) == 2, 'Expected exactly two native jobs.')
    jobs = {}
    for runner, expected_id in JOB_IDS.items():
        matching = [job for job in jobs_response['jobs'] if job['id'] == expected_id]
        require(len(matching) == 1, 'Expected native job ID is absent.')
        job = matching[0]
        require(job['run_id'] == RUN and job['run_attempt'] == ATTEMPT and job['head_sha'] == SHA
                and job['name'] == f'native-application ({runner})' and runner in job['labels'],
                'Native job identity differs.')
        jobs[runner] = job
    metadata = fetch(f'/actions/runs/{RUN}/artifacts?per_page=100', 'artifacts')
    require(type(metadata['total_count']) is int and metadata['total_count'] <= 100
            and len(metadata['artifacts']) == metadata['total_count'], 'Artifact pagination is incomplete.')

    STATE = ROOT / 'collector-artifact-state.json'
    state = parse_json(read_regular(STATE, 4 * 1024**2)) if STATE.exists() else {'runID': RUN, 'sourceSHA': SHA, 'runAttempt': ATTEMPT, 'attempts': {}}
    require((state['runID'], state['sourceSHA'], state['runAttempt']) == (RUN, SHA, ATTEMPT), 'Collector state belongs to another run.')


    def persist(): write(STATE, encode(state), replace=True)


    def policy(name):
        runner = next((candidate for candidate in JOB_IDS if name.endswith('-' + candidate)), None)
        require(runner is not None, 'Artifact runner is unexpected.')
        prefix = name[:-(len(runner) + 1)]
        if prefix in ('PDF-binary-validated', 'PDF-binary-unvalidated'): return runner, None, None, None
        if prefix == 'PDF-native-checks': allowed = required = {'PDF-native-checks.log'}; limit = 64 * 1024**2
        elif prefix == 'PDF-macOS-preview':
            allowed = required = {f'PDF-preview{"." + s if s else ""}.png' for s in PREVIEW_STATES} | set(REQUIRED_AX) | {'PDF-preview.revisao-ocr.source.pdf', 'PDF-preview.revisao-ocr.analysis.json'}
            limit = 128 * 1024**2
            require(len(allowed) == 42, 'Expected 42 preview files.')
        elif prefix == 'PDF-window-lifecycle':
            allowed = {}
            for stage in ('early', 'installed'):
                allowed.update({stage + '.json': 2 * 1024**2, stage + '-receipt.json': 64 * 1024,
                                stage + '.log': 64 * 1024**2})
            required = set(allowed); limit = 144 * 1024**2
        elif prefix == 'PDF-Apple-Vision-capability': allowed = required = {'PDF-vision-audit.json', 'PDF-vision-audit.log'}; limit = 32 * 1024**2
        elif prefix == 'PDF-local-AI': allowed = required = {'PDF-local-ai.json'}; limit = 32 * 1024**2
        elif prefix == 'PDF-macOS-benchmark': allowed = required = {'PDF-benchmark.json'}; limit = 32 * 1024**2
        elif prefix in ('PDF-source', 'PDF-source-ocr-compatibility', 'PDF-source-unvalidated'):
            required = {'PDF-source.tar.gz', 'PDF-source.tar.gz.sha256'}
            allowed = required | {'PDF-vision-audit.json', 'PDF-local-ai.json', 'PDF-benchmark.json'}; limit = 192 * 1024**2
            allowed = {item: (192 * 1024**2 if item == 'PDF-source.tar.gz' else 32 * 1024**2) for item in allowed}
            allowed['PDF-source.tar.gz.sha256'] = 1024
        else: raise ValueError('Unexpected artifact name: ' + name)
        return runner, (allowed if isinstance(allowed, dict) else dict.fromkeys(allowed, min(limit, 64 * 1024**2))), required, limit


    def inventory(path, allowed, limit):
        # Bound central-directory allocation before creating ZipFile, including
        # ZIP64. The shared extractor then validates exact flat names/types/CRC.
        size = path.stat().st_size
        with path.open('rb') as stream:
            length = min(size, 65557); stream.seek(size - length); tail = stream.read(length)
            offset = tail.rfind(b'PK\x05\x06')
            require(offset >= 0 and offset + 22 <= len(tail), 'ZIP end record is absent.')
            values = struct.unpack('<4s4H2IH', tail[offset:offset + 22]); count = values[4]
            if count == 65535:
                absolute = size - length + offset
                require(absolute >= 20, 'ZIP64 locator is absent.')
                stream.seek(absolute - 20); locator = struct.unpack('<4sIQI', stream.read(20))
                require(locator[0] == b'PK\x06\x07' and locator[2] + 56 <= absolute - 20, 'ZIP64 locator is invalid.')
                stream.seek(locator[2]); record = struct.unpack('<4sQ2H2I4Q', stream.read(56)); count = record[7]
            require(0 < count <= len(allowed), 'ZIP member count exceeds the known inventory.')
            _zip_directory(stream, size, count)
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                require(len(entries) == count and all(item.filename in allowed for item in entries), 'ZIP includes an unexpected filename.')
                require(sum(item.file_size for item in entries) <= limit, 'ZIP expanded total exceeds its bound.')
                require(all((0 if item.filename.endswith('.log') else 1) <= item.file_size <= allowed[item.filename]
                            for item in entries), 'ZIP member exceeds its per-file bound.')
                expected = {item.filename: allowed[item.filename] for item in entries}
                require(len(expected) == len(entries), 'ZIP repeats filenames.')
        return expected



    def validate_lifecycle(files, record, job):
        stages = {}
        scope_by_stage = {'early': 'minimal-diagnostic', 'installed': 'installed-application'}
        step_by_stage = {'early': 'Audit the real window early without installing the engine runtime',
                         'installed': 'Audit the real window in the complete installed application'}
        for stage, scope in scope_by_stage.items():
            names = {stage + '.json', stage + '-receipt.json', stage + '.log'}
            item = {'scope': scope, 'missingFiles': sorted(names - set(files)),
                    'reportReceiptValidated': False, 'workflowStepPassed': False, 'passed': False}
            stages[stage] = item
            if item['missingFiles']: continue
            try:
                raw = read_regular(files[stage + '.json'], 2 * 1024**2)
                native = validate_lifecycle_report(parse_json(raw))
                receipt = parse_json(read_regular(files[stage + '-receipt.json'], 64 * 1024))
                require(isinstance(receipt, dict) and type(receipt.get('schemaVersion')) is int
                        and receipt['schemaVersion'] == 1 and receipt.get('scope') == scope
                        and receipt.get('sourceCommit') == SHA and receipt.get('status') == 'passed',
                        'Lifecycle receipt schema, scope, source or status differs.')
                for flag in ('sourceCommitAuthenticatedByThisValidator', 'completeApplicationApproved',
                             'historicalTimeoutCauseDemonstrated', 'humanVoiceOverTested',
                             'previewArtifactsValidatedByThisReport'):
                    require(receipt.get(flag) is False, 'Lifecycle receipt overstates its scope: ' + flag)
                for key, expected_value in (('nativeDiagnosticDeadlineSeconds', 55), ('nativeCleanupMaximumSeconds', 3),
                                            ('externalDeadlineSeconds', 60)):
                    require(type(receipt.get(key)) is int and receipt[key] == expected_value, 'Lifecycle deadline differs: ' + key)
                require(receipt.get('sampleOnTimeout') is True, 'Lifecycle timeout sampling flag missing.')
                report_identity = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                require(receipt.get('report') == report_identity and type(receipt['report'].get('bytes')) is int,
                        'Lifecycle receipt does not bind the original report bytes.')
                bundle = receipt.get('installedBundleFiles')
                require(isinstance(bundle, dict) and set(bundle) == {'Contents/MacOS/PDF', 'Contents/Info.plist'},
                        'Lifecycle bundle receipt inventory differs.')
                for relative, cap in (('Contents/MacOS/PDF', 256 * 1024**2), ('Contents/Info.plist', 65536)):
                    entry = bundle[relative]
                    require(isinstance(entry, dict) and set(entry) == {'bytes', 'sha256'}
                            and type(entry['bytes']) is int and 0 < entry['bytes'] <= cap
                            and isinstance(entry['sha256'], str) and re.fullmatch('[0-9a-f]{64}', entry['sha256']),
                            'Lifecycle bundle identity is malformed: ' + relative)
                log = read_regular(files[stage + '.log'], 64 * 1024**2, allow_empty=True)
                require(b'PDF real WindowGroup lifecycle audit passed' in log
                        and ('All 12 real-window diagnostic checks passed: ' + scope).encode() in log,
                        'Lifecycle native/checker completion markers are missing.')
                step = [value for value in job['steps'] if value['name'] == step_by_stage[stage]]
                require(len(step) == 1, 'Lifecycle workflow step identity missing or duplicated.')
                workflow_passed = step[0]['status'] == 'completed' and step[0]['conclusion'] == 'success'
                item.update(reportReceiptValidated=True, workflowStepPassed=workflow_passed, passed=workflow_passed,
                            report=report_identity, reportChecks=len(native['checks']),
                            installedBundleFiles=bundle, bundleFilesIndependentlyRehashedHere=False,
                            totalMilliseconds=native['totalMilliseconds'], workflowStep=step[0]['name'])
            except (OSError, ValueError, KeyError, TypeError) as exception:
                # A failed/partial diagnostic is valuable original evidence, not an
                # approved diagnostic. Preserve it without manufacturing a receipt.
                item['validationError'] = str(exception)[:768]
        record.update(lifecycleStages=stages, lifecycleAllStagesPassed=all(item['passed'] for item in stages.values()),
            lifecycleValidationScope='Exact-source report checker, raw-report/receipt binding, declared source matched to authenticated run/job and original ZIP digest; bundle file hashes are original workflow assertions, not locally rehashed app binaries. No complete app, historical-cause, preview or human VoiceOver approval.')


    # Reject every unknown/duplicate artifact name before the first ZIP download,
    # including names in a later list entry; binary metadata is retained but deferred.
    artifact_ids = set(); artifact_names = set()
    for item in metadata['artifacts']:
        require(type(item.get('id')) is int and item['id'] > 0 and isinstance(item.get('name'), str),
                'Malformed artifact ID/name.')
        require(item['id'] not in artifact_ids and item['name'] not in artifact_names, 'Repeated artifact ID or name.')
        artifact_ids.add(item['id']); artifact_names.add(item['name']); policy(item['name'])


    available = []; deferred = []; processed = []
    for artifact in metadata['artifacts']:
        ident = artifact['id']; name = artifact['name']; size = artifact['size_in_bytes']; github_digest = artifact['digest']
        require(type(ident) is int and ident > 0 and type(size) is int and size > 0
                and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SHA
                and artifact['workflow_run']['head_repository_id'] == REPO_ID and artifact['expired'] is False
                and isinstance(github_digest, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', github_digest),
                'Artifact identity, expiry, size or digest is invalid.')
        runner, allowed, required, limit = policy(name); job = jobs[runner]
        require(timestamp(artifact['created_at']) >= timestamp(job['started_at'])
                and (job['completed_at'] is None or timestamp(artifact['created_at']) <= timestamp(job['completed_at']) + 5),
                'Artifact creation is outside its native job interval.')
        available.append({'id': ident, 'name': name, 'bytes': size, 'digest': github_digest, 'jobID': job['id']})
        if allowed is None:
            deferred.append({'name': name, 'reason': 'large-binary-not-authorized-for-this-collector'}); continue
        require(size <= limit, 'Artifact archive exceeds its size bound.')
        key = str(ident)
        if key in state['attempts']:
            prior = state['attempts'][key]
            require((prior['name'], prior['githubDigest'], prior['archiveBytes']) == (name, github_digest, size), 'An existing artifact identity changed.')
            # Even cached originals are rechecked against the current job snapshot; a prior in-progress step is not frozen as a failure.
            if not prior.get('downloaded') and prior.get('downloadAttempts', 0) >= 3:
                deferred.append({'name': name, 'reason': 'download-retry-limit'}); continue
        record = state['attempts'].setdefault(key, {'id': ident, 'name': name, 'runID': RUN, 'sourceSHA': SHA,
            'runAttempt': ATTEMPT, 'jobID': job['id'], 'archiveBytes': size, 'githubDigest': github_digest, 'downloadAttempts': 0})
        archive = ROOT / 'downloads' / (key + '.zip')
        if archive.exists():
            require(archive.stat().st_size == size and digest(archive) == github_digest[7:], 'Cached artifact digest/size differs.')
        else:
            record['downloadAttempts'] += 1; record['attemptedAt'] = time.time(); persist()
            temporary = archive.with_suffix('.zip.partial')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                def bounded(): resource.setrlimit(resource.RLIMIT_FSIZE, (size + 1024, size + 1024))
                with os.fdopen(fd, 'wb') as out:
                    try:
                        result = subprocess.run(['gh', 'api', API + f'/actions/artifacts/{ident}/zip'], stdout=out,
                            stderr=subprocess.PIPE, timeout=60, preexec_fn=bounded)
                    except subprocess.TimeoutExpired:
                        record['downloadError'] = {'timeoutSeconds': 60}; persist(); continue
                if result.returncode:
                    record['downloadError'] = error(result); persist()
                    print(json.dumps({'name': name, 'downloadError': record['downloadError']}), flush=True)
                    if set(record['downloadError']['http']) & {'401', '403'}:
                        raise RuntimeError('Authenticated artifact access was refused; originals preserved, no further downloads attempted.')
                    continue
                require(temporary.stat().st_size == size and digest(temporary) == github_digest[7:], 'Downloaded archive digest/size differs from authenticated GitHub metadata.')
                temporary.rename(archive)
            finally:
                if temporary.exists(): temporary.unlink()
        record.update(downloaded=True, archiveSHA256=digest(archive))
        expected = inventory(archive, allowed, limit)
        destination = ROOT / 'extracted' / name
        if destination.exists():
            require(record.get('extractionVerified') is True and destination.is_dir() and not destination.is_symlink(),
                    'Unexpected or incomplete existing extraction; preserve it for review.')
            previous_files = {item['name']: item for item in record['files']}
            require(set(previous_files) == set(expected) == {path.name for path in destination.iterdir()},
                    'Existing extraction inventory differs.')
            files = {}
            for relative, cap in expected.items():
                path = destination / relative
                raw = read_regular(path, cap, allow_empty=relative.endswith('.log'))
                require(len(raw) == previous_files[relative]['bytes']
                        and hashlib.sha256(raw).hexdigest() == previous_files[relative]['sha256'],
                        'An extracted original changed: ' + relative)
                files[relative] = path
        else:
            files = extract_zip(archive, destination, expected, total_limit=limit)
        missing = sorted(required - set(files))
        record.update(extractionVerified=True, directory=str(destination), missingRequiredFiles=missing,
            inventoryComplete=not missing, files=[{'name': item, 'bytes': path.stat().st_size, 'sha256': digest(path)} for item, path in sorted(files.items())])
        if name.startswith('PDF-macOS-preview-'):
            log = io.StringIO()
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log): previews_valid = check_directory(destination)
            write(SNAPSHOT / (name + '.validation.log'), log.getvalue().encode())
            source = destination / 'PDF-preview.revisao-ocr.source.pdf'; analysis = destination / 'PDF-preview.revisao-ocr.analysis.json'
            ocr_valid = source.is_file() and analysis.is_file()
            try:
                if ocr_valid:
                    ocr = json.loads(analysis.read_bytes())
                    ocr_valid = source.read_bytes().startswith(b'%PDF-') and isinstance(ocr, dict)
                    if ocr_valid:
                        content = dict(ocr); review_digest = content.pop('review_sha256', None)
                        computed = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
                        source_matches = ocr.get('source_sha256') == digest(source)
                        review_matches = review_digest == computed
                        words = ocr.get('words')
                        ocr_valid = source_matches and review_matches and type(ocr.get('version')) is int and ocr['version'] == 1 \
                            and isinstance(words, list) and 0 < len(words) <= 50000
                        record.update(ocrPairSourceSHA256Verified=source_matches, ocrReviewDigestVerified=review_matches,
                            ocrWordCount=len(words) if isinstance(words, list) else None)
            except (OSError, ValueError, TypeError) as exception:
                ocr_valid = False; record['ocrValidationError'] = str(exception)[:512]
            # Preserve both original OCR files; fingerprints do not constitute
            # human assessment of recognition quality.
            record.update(previewValidationPassed=previews_valid and not missing and ocr_valid,
                previewValidationScope='Exact inventory, PNG framing/CRC/raster, existing AX rules, OCR pair fingerprints; no human visual or VoiceOver approval.',
                previewPNGCount=sum(item.endswith('.png') for item in files),
                previewAXCount=sum(item.endswith('.accessibility.json') for item in files),
                previewOCRCount=sum(item in {'PDF-preview.revisao-ocr.source.pdf', 'PDF-preview.revisao-ocr.analysis.json'} for item in files))
        if name.startswith('PDF-window-lifecycle-'):
            validate_lifecycle(files, record, job)
        if name.startswith(('PDF-source-', 'PDF-source-ocr-compatibility-', 'PDF-source-unvalidated-')):
            record['sourceArchiveChecksumVerified'] = False
            if {'PDF-source.tar.gz', 'PDF-source.tar.gz.sha256'} <= set(files):
                actual = digest(files['PDF-source.tar.gz'])
                checksum = read_regular(files['PDF-source.tar.gz.sha256'], 1024)
                require(checksum == (actual + '  PDF-source.tar.gz\n').encode(), 'Original source archive checksum differs.')
                record['sourceArchiveChecksumVerified'] = True
        persist(); processed.append({'name': name, 'files': len(files), 'inventoryComplete': not missing,
                                     'previewValidationPassed': record.get('previewValidationPassed'),
                                     'lifecycleAllStagesPassed': record.get('lifecycleAllStagesPassed')})
        print(json.dumps(processed[-1]), flush=True)
    write(ROOT / 'collector-available-artifacts.json', encode(available), replace=True)
    summary = {'runID': RUN, 'sourceSHA': SHA, 'runAttempt': ATTEMPT, 'status': run['status'], 'conclusion': run['conclusion'],
        'jobs': [{'id': job['id'], 'name': job['name'], 'status': job['status'], 'conclusion': job['conclusion']} for job in jobs.values()],
        'publishedArtifacts': len(available), 'processedThisPass': processed, 'deferred': deferred,
        'verifiedArchives': sum(bool(item.get('extractionVerified')) for item in state['attempts'].values()),
        'snapshotDirectory': str(SNAPSHOT), 'noBinaryDownloaded': True, 'completeApplicationApproved': False}
    write(ROOT / 'collector-summary.json', encode(summary), replace=True)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
