#!/usr/bin/env python3
"""Retain original failed-CI evidence in a draft, never publish or execute it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time

RUNNERS = ('macos-26', 'xcode-27')
ARTIFACT_PREFIXES = ('PDF-native-checks-', 'PDF-macOS-preview-',
                    'PDF-Apple-Vision-capability-', 'PDF-local-AI-', 'PDF-macOS-benchmark-')
ARTIFACT_NAMES = tuple(prefix + runner for runner in RUNNERS for prefix in ARTIFACT_PREFIXES)
REQUIRED_STEPS = (
    'Verify installer integrity', 'Compile native application',
    'Install native PDF structural checker', 'Build, install and validate complete application',
    'Validate installed application and local OCR', 'Retain native diagnostic log',
    'Capture native window preview', 'Validate all native previews and accessibility reports',
    'Retain native preview artifact', 'Record Apple Vision capability independently',
    'Retain Apple Vision capability report',
    'Evaluate Portuguese answers with the actual local Apple model',
    'Retain local AI experiment and explicit availability',
    'Benchmark the installed application with OCR', 'Retain native benchmark artifact',
)
MAX_ARTIFACT = 256 * 1024 ** 2
MAX_LOG = 64 * 1024 ** 2
MAX_JSON = 8 * 1024 ** 2
MAX_DIAGNOSTIC = 16 * 1024
MANIFEST = 'evidence-provenance.json'


class EvidenceFailure(ValueError):
    """Only controlled messages are safe to print; never raw transport errors."""


def require(condition, message):
    if not condition:
        raise EvidenceFailure(message)


def positive_integer(value):
    return type(value) is int and value > 0


def download_failure(returncode, diagnostic):
    # Never print raw gh stderr: it may contain credentials or signed redirects.
    match = re.search(rb'\bHTTP\s+([1-5][0-9]{2})\b', diagnostic[:MAX_DIAGNOSTIC])
    status = match.group(1).decode('ascii') if match else 'unreported'
    return ('GitHub evidence download was rejected (API host=api.github.com; HTTP='
            + status + '; gh exit=' + str(returncode) + ').')


def validate_inputs(run_id, commit, repository):
    require(re.fullmatch(r'[1-9][0-9]{0,19}', run_id) is not None, 'Invalid source run ID.')
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'Full immutable source commit required.')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is not None,
            'Invalid repository identity.')
    require(all(part not in ('.', '..') for part in repository.split('/')), 'Invalid repository identity.')


def validate_origin(run, jobs, artifacts, run_id, commit, repository):
    validate_inputs(run_id, commit, repository)
    require(run.get('id') == int(run_id) and run.get('status') == 'completed'
            and run.get('conclusion') == 'failure', 'Only a completed failed source run is eligible.')
    require(run.get('head_sha') == commit and run.get('path') == '.github/workflows/macos.yml',
            'Source commit or workflow mismatch.')
    repo = run.get('repository', {})
    head = run.get('head_repository', {})
    require(repo.get('full_name') == repository and head.get('full_name') == repository
            and positive_integer(repo.get('id')) and head.get('id') == repo['id'],
            'Only evidence from this same repository is eligible.')
    require(positive_integer(run.get('run_attempt')), 'Missing source attempt identity.')
    expected_jobs = {'native-application (' + runner + ')': runner for runner in RUNNERS}
    require(len(jobs) == 2 and {job.get('name') for job in jobs} == set(expected_jobs),
            'The exact two native platform jobs are required.')
    chosen_jobs = {}
    for job in jobs:
        require(positive_integer(job.get('id')) and job.get('run_id') == int(run_id)
                and job.get('run_attempt') == run['run_attempt']
                and job.get('head_sha') == commit and job.get('status') == 'completed'
                and job.get('conclusion') in ('success', 'failure'), 'Invalid native job identity or state.')
        steps = job.get('steps')
        require(isinstance(steps, list), 'Missing native steps.')
        for name in REQUIRED_STEPS:
            matches = [step for step in steps if step.get('name') == name]
            require(len(matches) == 1 and matches[0].get('status') == 'completed'
                    and matches[0].get('conclusion') == 'success',
                    'A required native evidence gate did not succeed: ' + name)
        start, end = job.get('started_at'), job.get('completed_at')
        require(isinstance(start, str) and isinstance(end, str) and start < end,
                'Missing native job time interval.')
        chosen_jobs[expected_jobs[job['name']]] = job
    require(len({job['id'] for job in jobs}) == 2
            and any(job['conclusion'] == 'failure' for job in jobs), 'Contradictory native job results.')
    chosen = []
    for name in ARTIFACT_NAMES:
        matches = [item for item in artifacts if item.get('name') == name]
        require(len(matches) == 1, 'Missing or duplicate allowlisted artifact: ' + name)
        item = matches[0]
        require(positive_integer(item.get('id')) and item.get('expired') is False
                and positive_integer(item.get('size_in_bytes')) and item['size_in_bytes'] <= MAX_ARTIFACT,
                'Expired or invalid artifact: ' + name)
        require(isinstance(item.get('digest'), str)
                and re.fullmatch('sha256:[0-9a-f]{64}', item['digest']) is not None,
                'Missing artifact ZIP digest: ' + name)
        origin = item.get('workflow_run', {})
        require(origin.get('id') == int(run_id) and origin.get('head_sha') == commit
                and origin.get('repository_id') == repo['id']
                and origin.get('head_repository_id') == repo['id'], 'Foreign artifact origin: ' + name)
        runner = next(runner for runner in RUNNERS if name.endswith('-' + runner))
        created = item.get('created_at')
        require(isinstance(created, str)
                and chosen_jobs[runner]['started_at'] <= created <= chosen_jobs[runner]['completed_at'],
                'Artifact is outside the selected job attempt: ' + name)
        chosen.append(item)
    require(len({item['id'] for item in chosen}) == 10, 'Repeated artifact identity.')
    return chosen_jobs, chosen


class GitHub:
    """Use fixed GitHub API routes; gh errors/redirects never enter tool logs."""
    def __init__(self, repository):
        require(bool(os.environ.get('GITHUB_TOKEN')), 'The job GitHub token is missing.')
        self.repository = repository
        self.environment = os.environ.copy()
        for name in ('GH_TOKEN', 'GH_HOST', 'GH_DEBUG', 'GH_TRACE', 'GH_ENTERPRISE_TOKEN',
                     'GITHUB_ENTERPRISE_TOKEN'):
            self.environment.pop(name, None)
        self.environment.update(GH_PROMPT_DISABLED='1', GH_NO_UPDATE_NOTIFIER='1')

    def arguments(self, route, method='GET', accept='application/vnd.github+json'):
        require(route.startswith('/') and '\n' not in route, 'Invalid internal API route.')
        return ['gh', 'api', '--hostname', 'github.com', '--method', method,
                '--header', 'Accept: ' + accept,
                '--header', 'X-GitHub-Api-Version: 2022-11-28',
                'repos/' + self.repository + route]

    def json(self, route, method='GET', payload=None):
        arguments = self.arguments(route, method)
        data = None
        if payload is not None:
            arguments += ['--input', '-']
            data = json.dumps(payload).encode()
        try:
            result = subprocess.run(arguments, input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=self.environment, timeout=90)
        except (OSError, subprocess.SubprocessError):
            raise EvidenceFailure('GitHub metadata request could not complete.') from None
        require(result.returncode == 0, 'GitHub metadata request was rejected.')
        require(len(result.stdout) <= MAX_JSON, 'GitHub metadata exceeded the evidence limit.')
        try:
            return json.loads(result.stdout)
        except (UnicodeError, ValueError):
            raise EvidenceFailure('GitHub returned invalid evidence metadata.') from None

    def listing(self, route, maximum=2000):
        values = []
        for page in range(1, maximum // 100 + 2):
            result = self.json(route + '?per_page=100&page=' + str(page))
            require(isinstance(result, list), 'Invalid GitHub listing.')
            values.extend(result)
            require(len(values) <= maximum, 'GitHub listing exceeds the bounded complete inventory.')
            if len(result) < 100:
                return values
        raise EvidenceFailure('GitHub listing could not be completed.')

    def download(self, route, destination, limit, expected_bytes=None, expected_sha=None):
        # Do not extract ZIPs or execute any downloaded content. Bound the
        # stream before disk exhaustion; discard raw gh errors and signed URLs.
        process = None
        digest = hashlib.sha256()
        diagnostic = bytearray()
        count = 0
        created = False
        # Actions ZIP/log endpoints negotiate JSON metadata before redirecting;
        # requesting octet-stream there returns HTTP 415. Release assets require it.
        accept = ('application/octet-stream' if route.startswith('/releases/assets/')
                  else 'application/vnd.github+json')
        try:
            with destination.open('xb') as output:
                created = True
                process = subprocess.Popen(self.arguments(route, accept=accept),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.environment)
                deadline = time.monotonic() + 300
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, 'content')
                    selector.register(process.stderr, selectors.EVENT_READ, 'diagnostic')
                    while selector.get_map():
                        require(time.monotonic() < deadline, 'GitHub evidence download timed out.')
                        for key, _ in selector.select(timeout=1):
                            block = os.read(key.fd, 1024 * 1024)
                            if not block:
                                selector.unregister(key.fileobj)
                            elif key.data == 'diagnostic':
                                diagnostic.extend(block[:max(0, MAX_DIAGNOSTIC - len(diagnostic))])
                            else:
                                count += len(block)
                                require(count <= limit and (expected_bytes is None or count <= expected_bytes),
                                        'GitHub evidence download exceeded its declared size.')
                                digest.update(block); output.write(block)
                returncode = process.wait(timeout=10)
                require(returncode == 0, download_failure(returncode, diagnostic))
            require(count > 0 and (expected_bytes is None or count == expected_bytes),
                    'GitHub evidence download has the wrong size.')
            value = digest.hexdigest()
            require(expected_sha is None or value == expected_sha, 'GitHub evidence SHA-256 mismatch.')
            return {'name': destination.name, 'bytes': count, 'sha256': value}
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill(); process.wait()
            if created:
                destination.unlink(missing_ok=True)
            raise
        finally:
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    def upload(self, tag, path):
        # No --clobber: an asset appearing concurrently must make upload fail.
        try:
            result = subprocess.run(['gh', 'release', 'upload', tag, str(path),
                                     '--repo', 'github.com/' + self.repository], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=self.environment, timeout=300)
        except (OSError, subprocess.SubprocessError):
            raise EvidenceFailure('Draft evidence upload could not complete.') from None
        require(result.returncode == 0, 'Draft evidence upload failed; existing assets were not replaced.')


def release_description(run_id, commit):
    return ('Preservação de evidências originais do GitHub Actions.\n\n'
            'Resultado global da execução de origem: **FAILURE**. '
            'Isto não é uma versão aprovada do aplicativo nem um instalador.\n\n'
            'Execução: ' + run_id + '\nCommit: `' + commit + '`\n'
            'Workflow de origem: `.github/workflows/macos.yml`\n\n'
            'Apenas dez arquivos ZIP de evidência nativa, o ZIP original dos logs completos '
            'da tentativa validada e seu manifesto. '
            'Os ZIPs não são extraídos nem executados durante esta preservação. '
            'Resultados de IA indisponível e de capacidade Vision permanecem nos originais.\n\n'
            'Manter como rascunho. Não publicar nem substituir assets existentes.\n')


def validate_release(release, tag, commit, description):
    require(positive_integer(release.get('id')) and release.get('draft') is True
            and release.get('tag_name') == tag and release.get('target_commitish') == commit
            and release.get('body') == description and release.get('prerelease') is True,
            'Existing release is published, changed or belongs to another evidence export.')


def local_hash(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256(); count = 0
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_ARTIFACT,
                'Local evidence must be a bounded regular file.')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block); count += len(block)
        after = os.fstat(stream.fileno())
        require(count == before.st_size == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns, 'Local evidence changed during hashing.')
    return {'name': path.name, 'bytes': count, 'sha256': digest.hexdigest()}


def compare_existing_asset(api, asset, file, scratch):
    expected = local_hash(file)
    require(positive_integer(asset.get('id')) and asset.get('name') == file.name
            and asset.get('state') == 'uploaded' and asset.get('size') == expected['bytes'],
            'An existing draft asset has a different identity or size.')
    if asset.get('digest') is not None:
        require(asset['digest'] == 'sha256:' + expected['sha256'], 'Existing draft asset digest differs.')
    destination = scratch / ('existing-' + str(asset['id']))
    try:
        api.download('/releases/assets/' + str(asset['id']), destination, MAX_ARTIFACT,
                     expected_bytes=expected['bytes'], expected_sha=expected['sha256'])
    finally:
        destination.unlink(missing_ok=True)


def retain(api, run_id, commit, directory):
    base = '/actions/runs/' + run_id
    run = api.json(base)
    jobs = api.json(base + '/jobs?filter=latest&per_page=100')
    artifacts = api.json(base + '/artifacts?per_page=100')
    require(type(jobs.get('total_count')) is int and jobs['total_count'] == 2
            and len(jobs.get('jobs', [])) == 2, 'Incomplete native job inventory.')
    require(type(artifacts.get('total_count')) is int and 0 <= artifacts['total_count'] <= 100
            and len(artifacts.get('artifacts', [])) == artifacts['total_count'], 'Incomplete artifact inventory.')
    selected_jobs, selected = validate_origin(run, jobs['jobs'], artifacts['artifacts'],
                                              run_id, commit, api.repository)
    print('Authenticated failed source run:', run_id, 'commit:', commit, flush=True)
    directory.mkdir(mode=0o700)
    files = []
    for item in selected:
        print('Retaining original artifact:', item['name'], 'ID:', item['id'], flush=True)
        file = directory / (item['name'] + '.zip')
        record = api.download('/actions/artifacts/' + str(item['id']) + '/zip', file, MAX_ARTIFACT,
                              expected_bytes=item['size_in_bytes'], expected_sha=item['digest'][7:])
        files.append(dict(record, kind='original-artifact-zip', artifactID=item['id'],
                          artifactName=item['name'], githubDigest=item['digest']))
    job_records = []
    for runner in RUNNERS:
        job = selected_jobs[runner]
        job_records.append({'id': job['id'], 'runner': runner, 'conclusion': job['conclusion'],
                            'requiredNativeGatesPassed': list(REQUIRED_STEPS),
                            'failedSteps': [step['name'] for step in job['steps'] if step.get('conclusion') == 'failure']})
    # GitHub supplies the original full log ZIP for the verified attempt. Keep
    # its bytes opaque; do not reconstruct logs or stream ANSI text to a terminal.
    log_route = base + '/attempts/' + str(run['run_attempt']) + '/logs'
    print('Retaining original complete log ZIP for source attempt:', run['run_attempt'], flush=True)
    file = directory / ('source-run-' + run_id + '-attempt-' + str(run['run_attempt']) + '-logs.zip')
    record = api.download(log_route, file, MAX_LOG)
    files.append(dict(record, kind='original-complete-attempt-logs-zip', sourceAPIPath=log_route,
                      sourceRunID=int(run_id), sourceRunAttempt=run['run_attempt'],
                      jobIDs=[job['id'] for job in job_records],
                      digestProvenance='calculated-from-original-download; no upstream digest supplied'))
    manifest = {'schemaVersion': 2, 'purpose': 'original-evidence-retention-only',
                'repository': api.repository, 'sourceRunID': int(run_id), 'sourceCommit': commit,
                'sourceRunAttempt': run['run_attempt'], 'sourceWorkflow': run['path'],
                'sourceConclusion': 'failure', 'applicationApproved': False,
                'binaryDistributionApproved': False, 'archiveContentsExtractedOrExecuted': False,
                'jobs': job_records, 'files': files}
    with (directory / MANIFEST).open('x') as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True); stream.write('\n')
    tag = 'audit-' + commit[:12] + '-' + run_id
    description = release_description(run_id, commit)
    matches = [release for release in api.listing('/releases') if release.get('tag_name') == tag]
    require(len(matches) <= 1, 'Ambiguous existing evidence releases.')
    if matches:
        release = matches[0]
    else:
        release = api.json('/releases', 'POST', {'tag_name': tag, 'target_commitish': commit,
            'name': 'Evidências de CI reprovado · ' + run_id, 'body': description,
            'draft': True, 'prerelease': True, 'make_latest': 'false'})
    validate_release(release, tag, commit, description)
    paths = [directory / item['name'] for item in files] + [directory / MANIFEST]
    assets = api.listing('/releases/' + str(release['id']) + '/assets', maximum=1000)
    names = [asset.get('name') for asset in assets]
    require(len(set(names)) == len(names) and set(names).issubset({path.name for path in paths}),
            'Existing draft contains duplicate or unexpected assets; nothing will be overwritten.')
    by_name = {asset['name']: asset for asset in assets}
    # Compare all existing content before uploading any missing asset. A rerun
    # can complete an interrupted export, but cannot replace different bytes.
    for path in paths:
        if path.name in by_name:
            compare_existing_asset(api, by_name[path.name], path, directory)
    for path in paths:
        validate_release(api.json('/releases/' + str(release['id'])), tag, commit, description)
        if path.name not in by_name:
            api.upload(tag, path)
    validate_release(api.json('/releases/' + str(release['id'])), tag, commit, description)
    final = api.listing('/releases/' + str(release['id']) + '/assets', maximum=1000)
    require(len(final) == len(paths) and {asset.get('name') for asset in final} == {path.name for path in paths},
            'Draft evidence inventory is incomplete.')
    for asset in final:
        compare_existing_asset(api, asset, directory / asset['name'], directory)
    validate_release(api.json('/releases/' + str(release['id'])), tag, commit, description)
    return {'releaseID': release['id'], 'tag': tag, 'draft': True,
            'sourceRunID': int(run_id), 'sourceConclusion': 'failure', 'applicationApproved': False,
            'verifiedAssets': len(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        run_id, commit = os.environ['PDF_SOURCE_RUN_ID'], os.environ['PDF_SOURCE_COMMIT']
        repository = os.environ['GITHUB_REPOSITORY']
        validate_inputs(run_id, commit, repository)
        result = retain(GitHub(repository), run_id, commit, args.directory)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('release_id=' + str(result['releaseID']) + '\n')
                output.write('release_tag=' + result['tag'] + '\n')
        print(json.dumps(result, sort_keys=True))
    except EvidenceFailure as error:
        parser.exit(1, 'Evidence retention refused: ' + str(error) + '\n')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        # Do not echo arbitrary API payloads, command errors, tokens or redirects.
        parser.exit(1, 'Evidence retention failed. No release was published or existing asset overwritten.\n')


if __name__ == '__main__':
    main()
