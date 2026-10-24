#!/usr/bin/env python3
"""Bind a cross-OS binary test to one approved same-repository Actions run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import urllib.error
import urllib.request

ARTIFACT = 'PDF-binary-validated-macos-26'
ARCHIVE = 'PDF-arm64.tar.gz'
MAX_ARCHIVE = 12 * 1024 ** 3
MAX_MANIFEST = 32 * 1024 ** 2
REQUIRED_CHECKS = ('isolatedRuntimePassed', 'freshInstallPassed',
                   'transactionalUpdatePassed', 'preferencesPreserved',
                   'wrongChecksumRejected', 'appIntentsMetadataVerified')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_inputs(run_id, commit, expected_sha, repository):
    require(re.fullmatch(r'[1-9][0-9]{0,19}', run_id) is not None, 'Invalid source run ID.')
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'Full immutable source commit required.')
    require(re.fullmatch('[0-9a-f]{64}', expected_sha) is not None, 'Full expected SHA-256 required.')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is not None,
            'Invalid repository identity.')


def regular_bytes(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit,
                'Evidence must be a bounded regular file.')
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        require(len(data) == before.st_size and before.st_size == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns, 'Evidence changed during reading.')
        return data


def regular_json(path, limit=MAX_MANIFEST):
    result = json.loads(regular_bytes(path, limit))
    require(isinstance(result, dict), 'JSON evidence must be an object.')
    return result


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def api(repository, suffix):
    # Only GitHub's normal repository API is used. Do not follow an API response
    # to another host or expose tokens/redirect URLs in diagnostic output.
    token = os.environ.get('GH_TOKEN', '')
    require(bool(token), 'The read-only Actions token is missing.')
    request = urllib.request.Request('https://api.github.com/repos/' + repository + suffix,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'PDF-portable-compatibility'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            data = response.read(8 * 1024 ** 2 + 1)
        require(len(data) <= 8 * 1024 ** 2, 'GitHub response exceeded the evidence limit.')
        return json.loads(data)
    except urllib.error.HTTPError as error:
        raise ValueError('GitHub evidence API returned HTTP ' + str(error.code) + '.') from None
    except urllib.error.URLError:
        raise ValueError('GitHub evidence API could not be reached.') from None


def validate_origin(run, jobs, artifacts, run_id, commit, repository):
    require(run.get('id') == int(run_id), 'Source run identity mismatch.')
    require(run.get('status') == 'completed' and run.get('conclusion') == 'success',
            'The complete source workflow must already have succeeded.')
    require(run.get('head_sha') == commit, 'Source commit mismatch.')
    require(run.get('path') == '.github/workflows/macos.yml', 'Unexpected source workflow.')
    require(run.get('repository', {}).get('full_name') == repository
            and run.get('head_repository', {}).get('full_name') == repository,
            'Only a same-repository source build is allowed.')
    expected_jobs = {'native-application (macos-26)', 'native-application (xcode-27)'}
    selected_jobs = [job for job in jobs if job.get('name') in expected_jobs]
    require(len(selected_jobs) == 2 and {job.get('name') for job in selected_jobs} == expected_jobs
            and all(job.get('status') == 'completed' and job.get('conclusion') == 'success'
                    for job in selected_jobs), 'Both original platform jobs must have succeeded.')
    selected = [item for item in artifacts if item.get('name') == ARTIFACT]
    require(len(selected) == 1, 'Exactly one approved macOS 26 binary artifact is required.')
    artifact = selected[0]
    require(type(artifact.get('id')) is int and artifact['id'] > 0
            and artifact.get('expired') is False
            and type(artifact.get('size_in_bytes')) is int
            and 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE,
            'The approved artifact is expired or has an invalid size/identity.')
    origin = artifact.get('workflow_run', {})
    require(origin.get('id') == int(run_id) and origin.get('head_sha') == commit,
            'Artifact is not attached to the exact source run and commit.')
    return {'schemaVersion': 1, 'repository': repository, 'sourceRunID': int(run_id),
            'sourceCommit': commit, 'sourceWorkflow': run['path'],
            'sourceArtifactID': artifact['id'], 'sourceArtifactName': ARTIFACT,
            'sourceArtifactBytes': artifact['size_in_bytes'], 'sourceRunner': 'macos-26'}


def collect_origin(run_id, commit, expected_sha, repository):
    validate_inputs(run_id, commit, expected_sha, repository)
    base = '/actions/runs/' + run_id
    run = api(repository, base)
    jobs = api(repository, base + '/jobs?filter=latest&per_page=100')
    artifacts = api(repository, base + '/artifacts?per_page=100')
    require(jobs.get('total_count', 101) <= 100 and artifacts.get('total_count', 101) <= 100,
            'Source evidence needs pagination; refusing an incomplete evidence set.')
    result = validate_origin(run, jobs.get('jobs', []), artifacts.get('artifacts', []),
                             run_id, commit, repository)
    result['expectedArchiveSHA256'] = expected_sha
    return result


def verify_archive(directory, origin):
    commit = origin['sourceCommit']
    expected_sha = origin['expectedArchiveSHA256']
    checksum = regular_bytes(directory / (ARCHIVE + '.sha256'), 256).decode('ascii')
    require(checksum == expected_sha + '  ' + ARCHIVE + '\n', 'Published checksum mismatch.')
    archive = directory / ARCHIVE
    descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_ARCHIVE,
                'Archive is not a regular file within the size limit.')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        require(digest.hexdigest() == expected_sha, 'Archive SHA-256 does not match the independent input.')
        # Read only the manifest from the authenticated archive, without
        # extraction or execution. Reject duplicate manifests as ambiguous.
        stream.seek(0)
        internal = []
        members = 0
        expanded_bytes = 0
        with tarfile.open(fileobj=stream, mode='r|gz') as tar:
            for member in tar:
                members += 1
                expanded_bytes += member.size
                require(members <= 250000, 'Archive has too many members.')
                require(0 <= member.size <= MAX_ARCHIVE and expanded_bytes <= MAX_ARCHIVE,
                        'Expanded archive exceeds the allowed size.')
                if member.name == 'PDF-distribution/manifest.json':
                    require(member.isfile() and 0 < member.size <= MAX_MANIFEST,
                            'Internal manifest is not a bounded regular file.')
                    internal.append(json.loads(tar.extractfile(member).read(MAX_MANIFEST + 1)))
        after = os.fstat(stream.fileno())
        require(before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns,
                'Archive changed during verification.')
    manifest = regular_json(directory / 'distribution-manifest.json')
    require(internal == [manifest], 'Published manifest does not match the sole archive manifest.')
    require(manifest.get('schemaVersion') == 1 and manifest.get('architecture') == 'arm64'
            and manifest.get('commit') == commit and isinstance(manifest.get('files'), dict)
            and 0 < len(manifest['files']) <= 200000, 'Source manifest identity mismatch.')
    validation = regular_json(directory / 'distribution-validation.json', 1024 * 1024)
    require(validation.get('schemaVersion') == 1 and validation.get('commit') == commit
            and validation.get('runner') == 'macos-26', 'Source validation identity mismatch.')
    require(all(validation.get(check) is True for check in REQUIRED_CHECKS),
            'A mandatory source binary check was not approved.')
    require(validation.get('developerToolsOnDestinationRequired') is False
            and validation.get('appleNotarized') is False and validation.get('signing') == 'ad-hoc'
            and validation.get('manifestEntries') == len(manifest['files']),
            'Source validation claims are inconsistent.')
    return dict(origin, archiveSHA256=expected_sha, archiveBytes=before.st_size,
                archiveManifestMatched=True, sourceValidationMatched=True,
                manifestEntries=len(manifest['files']),
                applicationVersion=validation.get('applicationVersion'))


def report(verified, destination):
    def value(*arguments):
        return subprocess.check_output(arguments, text=True, timeout=30).strip()
    require(value('/usr/bin/uname', '-m') == 'arm64', 'Target must execute natively on arm64.')
    operating_system = value('/usr/bin/sw_vers', '-productVersion')
    require(operating_system.split('.')[0] == '27', 'This cross-OS test requires macOS 27.')
    result = dict(verified, schemaVersion=1, crossOSTestPassed=True,
                  targetRunner='xcode-27', targetOperatingSystem=operating_system,
                  targetProcessor=value('/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'),
                  targetLogicalCPUs=int(value('/usr/sbin/sysctl', '-n', 'hw.ncpu')),
                  architecture='arm64', freshInstallPassed=True, isolatedRuntimePassed=True,
                  appIntentsMetadataVerified=True, nativeSmokePassed=True,
                  rebuiltOnDestination=False, developerToolsOnDestinationRequired=False,
                  appleNotarized=False, signing='ad-hoc', physicalM4Measured=False,
                  neuralEngineMeasured=False, humanVoiceOverTested=False)
    write_json(destination, result)
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('origin', 'archive', 'report'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    try:
        if args.operation == 'origin':
            result = collect_origin(os.environ['PDF_SOURCE_RUN_ID'], os.environ['PDF_SOURCE_COMMIT'],
                                    os.environ['PDF_EXPECTED_SHA'], os.environ['GITHUB_REPOSITORY'])
            write_json(args.output, result)
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('artifact_id=' + str(result['sourceArtifactID']) + '\n')
            print('Approved source run:', result['sourceRunID'], 'commit:', result['sourceCommit'])
        elif args.operation == 'archive':
            result = verify_archive(args.directory, regular_json(args.input, 32768))
            write_json(args.output, result)
            print('Authenticated source archive SHA-256:', result['archiveSHA256'])
        else:
            report(regular_json(args.input, 32768), args.output)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Cross-OS evidence rejected: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
