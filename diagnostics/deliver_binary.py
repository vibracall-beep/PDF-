#!/usr/bin/env python3
"""Retain one cross-tested binary in a draft; never publish or rebuild it."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import cross_gui_evidence as gui
import delivery_archives
import delivery_parts
import portable_compatibility as portable
import retain_evidence as evidence

require = evidence.require
MAX_ARCHIVE = portable.MAX_ARCHIVE
LARGE_TIMEOUT = 1800
PROVENANCE = 'delivery-provenance.json'
CHECKSUMS = 'DELIVERY-SHA256SUMS'
SOURCE_WORKFLOW = '.github/workflows/macos.yml'
CROSS_WORKFLOW = '.github/workflows/portable-compatibility.yml'
SOURCE_NAMES = ('PDF-source-macos-26', 'PDF-source-ocr-compatibility-macos-26')
SOURCE_JOBS = tuple('native-application (' + runner + ')' for runner in evidence.RUNNERS)
SOURCE_STEPS = evidence.REQUIRED_STEPS + (
    'Assemble relocatable binary distribution',
    'Validate portable app without host dependencies or network',
    'Package and verify binary install and update',
    'Retain binary package with explicit validation status',
    'Create source distribution', 'Retain source artifact with validation status',
)
CROSS_STEPS = (
    'Check out this validation control',
    'Authenticate the completed source run and approved macOS 26 artifact',
    'Check out only the authenticated source commit for installation checks',
    'Download the exact approved same-repository artifact',
    'Verify the independent hash and both internal and published evidence',
    'Install the unchanged macOS 26 binary on macOS 27',
    'Deny host dependencies and validate runtime, metadata and native operations',
    'Bind the installed GUI to the unchanged authenticated archive',
    'Capture the installed binary GUI once outside the dependency sandbox',
    'Validate and bind all original GUI artifacts',
    'Publish the exact cross-OS measurement and target hardware identity',
    'Retain evidence without relabeling a failed installation',
)
BINARY_CONTENTS = {portable.ARCHIVE: MAX_ARCHIVE, portable.ARCHIVE + '.sha256': 256,
                   'install-binary.sh': 1024 ** 2, 'distribution-manifest.json': portable.MAX_MANIFEST,
                   'distribution-validation.json': 1024 ** 2}
SOURCE_CONTENTS = {'PDF-source.tar.gz': 128 * 1024 ** 2, 'PDF-source.tar.gz.sha256': 256,
                   'PDF-vision-audit.json': 1024 ** 2, 'PDF-benchmark.json': 1024 ** 2,
                   'PDF-local-ai.json': 1024 ** 2}
CROSS_CONTENTS = {'PDF-cross-origin.json': 32768, 'PDF-cross-verified.json': 32768,
                  'PDF-cross-isolation.log': evidence.MAX_LOG, 'PDF-cross-platform.json': 32768, **gui.GUI_CONTENTS}
LIMITATIONS = (
    'Os checks comprovam instalação e isolamento do pacote nos runners identificados; '
    'não comprovam desempenho em M4 físico, uso da Neural Engine ou auditoria humana com VoiceOver. '
    'IA local pode permanecer indisponível, conforme os relatórios originais. '
    'Recursos com escopo parcial e integrações opcionais continuam descritos nos fontes e relatórios. '
    'Assinatura ad hoc, sem notarização Apple; políticas do Gatekeeper permanecem ativas.'
)


def validate_inputs(source_run, source_commit, expected_sha, cross_run, cross_commit, repository):
    evidence.validate_inputs(source_run, source_commit, repository)
    evidence.validate_inputs(cross_run, cross_commit, repository)
    require(source_run != cross_run, 'Source and cross-platform runs must be distinct.')
    require(re.fullmatch('[0-9a-f]{64}', expected_sha) is not None, 'Independent full archive SHA-256 required.')


def moment(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value),
            'Missing canonical GitHub evidence timestamp.')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def validate_run(run, jobs, run_id, commit, repository, workflow, names, required_steps):
    require(run.get('id') == int(run_id) and run.get('head_sha') == commit
            and run.get('path') == workflow and run.get('status') == 'completed'
            and run.get('conclusion') == 'success', 'Run identity, workflow or successful state mismatch.')
    repo, head = run.get('repository', {}), run.get('head_repository', {})
    require(repo.get('full_name') == head.get('full_name') == repository
            and evidence.positive_integer(repo.get('id')) and repo['id'] == head.get('id'),
            'Only a same-repository run is eligible for delivery.')
    require(evidence.positive_integer(run.get('run_attempt')), 'Missing run attempt identity.')
    require(len(jobs) == len(names) and {job.get('name') for job in jobs} == set(names),
            'The complete expected job inventory is required.')
    require(len({job.get('id') for job in jobs}) == len(jobs), 'Repeated job identity.')
    for job in jobs:
        require(evidence.positive_integer(job.get('id')) and job.get('run_id') == int(run_id)
                and job.get('run_attempt') == run['run_attempt'] and job.get('head_sha') == commit
                and job.get('status') == 'completed' and job.get('conclusion') == 'success',
                'A required job did not succeed in the exact requested attempt.')
        require(moment(job.get('started_at')) < moment(job.get('completed_at')), 'Invalid job time interval.')
        steps = job.get('steps')
        require(isinstance(steps, list), 'Missing required validation steps.')
        for name in required_steps:
            matches = [step for step in steps if step.get('name') == name]
            require(len(matches) == 1 and matches[0].get('status') == 'completed'
                    and matches[0].get('conclusion') == 'success', 'Required gate did not succeed: ' + name)
    return {job['name']: job for job in jobs}


def inventory(response, field, maximum=100):
    values = response.get(field)
    require(type(response.get('total_count')) is int and isinstance(values, list)
            and 0 <= response['total_count'] <= maximum and len(values) == response['total_count'],
            'Refusing an incomplete GitHub evidence inventory.')
    return values


def collect_run(api, run_id, commit, workflow, names, steps):
    base = '/actions/runs/' + run_id
    run = api.json(base)
    require(evidence.positive_integer(run.get('run_attempt')), 'Missing run attempt identity.')
    jobs = inventory(api.json(base + '/attempts/' + str(run['run_attempt']) + '/jobs?per_page=100'), 'jobs')
    selected_jobs = validate_run(run, jobs, run_id, commit, api.repository, workflow, names, steps)
    artifacts = inventory(api.json(base + '/artifacts?per_page=100'), 'artifacts')
    return run, selected_jobs, artifacts


def select_artifact(artifacts, names, run, job, maximum):
    matches = [item for item in artifacts if item.get('name') in names]
    require(len(matches) == 1, 'Missing or ambiguous approved evidence artifact.')
    item = matches[0]
    require(evidence.positive_integer(item.get('id')) and item.get('expired') is False
            and evidence.positive_integer(item.get('size_in_bytes')) and item['size_in_bytes'] <= maximum
            and isinstance(item.get('digest'), str) and re.fullmatch('sha256:[0-9a-f]{64}', item['digest']),
            'Invalid, expired or oversized evidence artifact.')
    origin = item.get('workflow_run', {})
    require(origin.get('id') == run['id'] and origin.get('head_sha') == run['head_sha']
            and origin.get('repository_id') == run['repository']['id']
            and origin.get('head_repository_id') == run['repository']['id'], 'Artifact origin mismatch.')
    require(moment(job['started_at']) <= moment(item.get('created_at')) <= moment(job['completed_at']),
            'Artifact belongs to a different job attempt.')
    return item


def collect_origins(api, source_id, commit, expected_sha, cross_id, cross_commit):
    validate_inputs(source_id, commit, expected_sha, cross_id, cross_commit, api.repository)
    source, jobs, artifacts = collect_run(api, source_id, commit, SOURCE_WORKFLOW, SOURCE_JOBS, SOURCE_STEPS)
    binary = select_artifact(artifacts, (portable.ARTIFACT,), source, jobs[SOURCE_JOBS[0]], MAX_ARCHIVE)
    other = select_artifact(artifacts, ('PDF-binary-validated-xcode-27',), source, jobs[SOURCE_JOBS[1]], MAX_ARCHIVE)
    source_artifact = select_artifact(artifacts, SOURCE_NAMES, source, jobs[SOURCE_JOBS[0]], evidence.MAX_ARTIFACT)
    native = []
    for name in evidence.ARTIFACT_NAMES:
        runner = next(value for value in evidence.RUNNERS if name.endswith('-' + value))
        native.append(select_artifact(artifacts, (name,), source,
                      jobs['native-application (' + runner + ')'], evidence.MAX_ARTIFACT))
    require(len({item['id'] for item in [binary, other, source_artifact] + native}) == 13,
            'Repeated source artifact identity.')
    cross, cross_jobs, cross_artifacts = collect_run(api, cross_id, cross_commit, CROSS_WORKFLOW,
                                                    ('compatible-binary',), CROSS_STEPS)
    cross_artifact = select_artifact(cross_artifacts, ('PDF-cross-platform-validated',), cross,
                                    cross_jobs['compatible-binary'], evidence.MAX_ARTIFACT)
    origin = portable.validate_origin(source, list(jobs.values()), artifacts, source_id, commit, api.repository)
    origin['expectedArchiveSHA256'] = expected_sha
    return {'source': source, 'sourceJobs': jobs, 'binary': binary, 'otherBinary': other,
            'sourceArtifact': source_artifact, 'native': native, 'cross': cross,
            'crossJobs': cross_jobs, 'crossArtifact': cross_artifact, 'origin': origin}


def verify_cross_reports(directory, origin, verified, manifest, source_verified):
    original = portable.regular_json(directory / 'PDF-cross-origin.json', 32768)
    intermediate = portable.regular_json(directory / 'PDF-cross-verified.json', 32768)
    report = portable.regular_json(directory / 'PDF-cross-platform.json', 32768)
    require(all(original.get(key) == value for key, value in origin.items()), 'Cross-test source identity mismatch.')
    for document in (intermediate, report):
        require(all(document.get(key) == value for key, value in verified.items()),
                'Cross-test did not validate the exact source archive and manifest.')
    require(report.get('crossOSTestPassed') is True and report.get('targetRunner') == 'xcode-27'
            and report.get('architecture') == 'arm64'
            and isinstance(report.get('targetOperatingSystem'), str)
            and re.fullmatch(r'27(?:\.\d+){0,2}', report['targetOperatingSystem'])
            and isinstance(report.get('targetProcessor'), str) and bool(report['targetProcessor'].strip())
            and evidence.positive_integer(report.get('targetLogicalCPUs')),
            'Cross-test target or successful result mismatch.')
    for name in ('freshInstallPassed', 'isolatedRuntimePassed', 'appIntentsMetadataVerified', 'nativeSmokePassed'):
        require(report.get(name) is True, 'Missing mandatory cross-platform check: ' + name)
    require(report.get('rebuiltOnDestination') is False and report.get('developerToolsOnDestinationRequired') is False
            and report.get('appleNotarized') is False and report.get('signing') == 'ad-hoc',
            'Cross-test execution or signature claims are inconsistent.')
    require(bool(portable.regular_bytes(directory / 'PDF-cross-isolation.log', evidence.MAX_LOG)),
            'The original isolation log is missing.')
    try:
        receipt = gui.verify_receipt(directory, verified, manifest)
        require(receipt['sourceScripts'] == {name: source_verified['additionalSourceFiles'].get('scripts/' + name)
                                            for name in gui.SCRIPT_NAMES},
                'GUI scripts differ from the authenticated original source archive.')
        require(report.get('installedBinaryGUIPassed') is True and report.get('guiOutsideDependencySandbox') is True
                and report.get('guiReceiptSHA256') == gui.hashed_file(directory / gui.RECEIPT, 32768)['sha256'],
                'Cross report does not bind the mandatory installed-binary GUI evidence.')
        for key, expected in (('guiCaptureAttempts', 1), ('guiCaptureDeadlineSeconds', 300),
                              ('guiPNGCount', 32), ('guiOwnWindowAXCount', 6), ('guiOriginalOCRFileCount', 2)):
            require(type(report.get(key)) is int and report[key] == expected, 'Invalid cross GUI contract: ' + key)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise evidence.EvidenceFailure('Cross GUI evidence rejected: ' + str(error)) from error
    return report


def artifact_record(item):
    return {key: item[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'created_at')}


def run_record(run, jobs):
    return {'id': run['id'], 'attempt': run['run_attempt'], 'commit': run['head_sha'],
            'workflow': run['path'], 'conclusion': run['conclusion'],
            'jobs': [{'id': job['id'], 'name': job['name'], 'conclusion': job['conclusion'],
                      'startedAt': job['started_at'], 'completedAt': job['completed_at']}
                     for job in jobs.values()]}


def description(source_id, commit, cross_id, cross_commit, sha):
    return ('Entrega ao proprietário após os checks binários da matriz macOS e o teste do mesmo '
            'arquivo macOS 26 no macOS 27. Rascunho, sem publicação pública.\n\n'
            'Origem: ' + source_id + ' · commit `' + commit + '`\n'
            'Cross-OS: ' + cross_id + ' · controle `' + cross_commit + '`\n'
            'SHA-256 do tar original: `' + sha + '`\n\n' + LIMITATIONS + '\n\n'
            'Fontes, evidências e avisos/licenças originais são preservados. '
            'Esta entrega não acrescenta licença ao aplicativo. Não publicar nem substituir assets.\n')


def download_artifact(api, item, destination, limit):
    require(shutil.disk_usage(destination.parent).free >= item['size_in_bytes'] + 64 * 1024 ** 2,
            'Insufficient free space for the authenticated artifact.')
    return api.download('/actions/artifacts/' + str(item['id']) + '/zip', destination, limit,
                        item['size_in_bytes'], item['digest'][7:], timeout=LARGE_TIMEOUT)


def write_json(path, value):
    with path.open('x') as output:
        json.dump(value, output, indent=2, sort_keys=True); output.write('\n')


def prepare(api, origins, directory):
    directory.mkdir(mode=0o700)
    incoming = directory / 'incoming'; incoming.mkdir(mode=0o700)
    payload = directory / 'payload'; payload.mkdir(mode=0o700)
    files, records = {}, {}

    def add(path, kind, measured=None):
        require(path.name not in records, 'Duplicate delivery asset name.')
        record = measured or evidence.local_hash(path, MAX_ARCHIVE)
        records[path.name] = dict(record, kind=kind)
        files[path.name] = path

    extracted = {}
    for key, expected, limit in (('binary', BINARY_CONTENTS, MAX_ARCHIVE),
                                 ('sourceArtifact', SOURCE_CONTENTS, evidence.MAX_ARTIFACT),
                                 ('crossArtifact', CROSS_CONTENTS, evidence.MAX_ARTIFACT)):
        item = origins[key]
        archive = incoming / (item['name'] + '.zip')
        download_artifact(api, item, archive, limit)
        destination = payload / key
        extracted[key] = delivery_archives.extract_zip(archive, destination, expected)
        if key == 'crossArtifact':
            add(archive, 'original-cross-platform-artifact-zip')
        else:
            archive.unlink()  # Only this job's verified transport ZIP; tar bytes stay unchanged.
    binary_dir = payload / 'binary'
    verified = portable.verify_archive(binary_dir, origins['origin'])
    manifest = portable.regular_json(binary_dir / 'distribution-manifest.json')
    validation = portable.regular_json(binary_dir / 'distribution-validation.json', 1024 ** 2)
    source_verified = delivery_archives.verify_source_and_installer(payload / 'sourceArtifact', binary_dir,
                                                                  origins['source']['head_sha'], manifest,
                                                                  required_source_files=tuple('scripts/' + name for name in gui.SCRIPT_NAMES))
    cross_report = verify_cross_reports(payload / 'crossArtifact', origins['origin'], verified, manifest, source_verified)
    original = binary_dir / portable.ARCHIVE
    plan = delivery_parts.plan_parts(original)
    require(plan['sha256'] == origins['origin']['expectedArchiveSHA256'] == verified['archiveSHA256']
            and plan['bytes'] == verified['archiveBytes'], 'Delivery bytes differ from the cross-tested binary.')
    for name, path in extracted['binary'].items():
        if name != portable.ARCHIVE:
            add(path, 'original-binary-artifact-file')
    for name in ('PDF-source.tar.gz', 'PDF-source.tar.gz.sha256'):
        add(extracted['sourceArtifact'][name], 'original-source-artifact-file')
    for path in extracted['crossArtifact'].values():
        add(path, 'original-cross-platform-gui-evidence' if path.name in gui.GUI_CONTENTS else 'original-cross-platform-report')
    if plan['mode'] == 'single':
        add(original, 'original-binary-tar', {'name': portable.ARCHIVE, 'bytes': plan['bytes'], 'sha256': plan['sha256']})
    else:
        for part in plan['parts']:
            records[part['name']] = dict(part, kind='original-binary-byte-part')
        script = payload / 'reassemble-binary.sh'
        with script.open('xb') as output: output.write(delivery_parts.reassembly_script(plan))
        add(script, 'verified-byte-reassembly-instructions')
    for item in origins['native']:
        target = incoming / (item['name'] + '.zip')
        measured = download_artifact(api, item, target, evidence.MAX_ARTIFACT)
        add(target, 'original-native-evidence-zip', measured)
    logs = []
    for label in ('source', 'cross'):
        run = origins[label]
        route = '/actions/runs/' + str(run['id']) + '/attempts/' + str(run['run_attempt']) + '/logs'
        target = incoming / (label + '-run-' + str(run['id']) + '-attempt-' + str(run['run_attempt']) + '-logs.zip')
        measured = api.download(route, target, evidence.MAX_LOG, timeout=LARGE_TIMEOUT)
        add(target, 'original-complete-attempt-logs-zip', measured)
        logs.append(dict(measured, sourceAPIPath=route,
                         digestProvenance='calculated-from-original-download; no upstream digest supplied'))
    notices = {name: value for name, value in manifest['files'].items()
               if '/runtime/' in name and (Path(name).name in ('THIRD-PARTY.json', 'THIRD-PARTY.txt')
               or re.search(r'(?i)(?:^|/)(?:licen[cs]e|copying|copyright|notice)(?:[./_-]|$)', name))}
    require(any(name.endswith('/runtime/THIRD-PARTY.json') for name in notices)
            and any(name.endswith('/runtime/THIRD-PARTY.txt') for name in notices),
            'Original third-party notices are missing from the authenticated package manifest.')
    instructions = payload / 'INSTALLATION.txt'
    text = ('Pacote de instalação: bytes originais testados em macOS 26 e 27.\n'
            'Baixe os assets deste rascunho pelo GitHub autenticado. Confira os hashes antes de executar scripts.\n'
            'SHA-256 do instalador: ' + source_verified['installerSHA256'] + '\n'
            'SHA-256 do tar completo: ' + plan['sha256'] + '\n')
    if plan['mode'] == 'byte-parts':
        text += 'Na pasta dos assets, execute: bash reassemble-binary.sh\nUse o caminho do tar informado pela recomposição.\n'
    text += ('Instale com: bash install-binary.sh /caminho/PDF-arm64.tar.gz ' + plan['sha256']
             + '\nO destino não exige Xcode, Homebrew, Git ou Python do sistema.\n' + LIMITATIONS + '\n')
    with instructions.open('x') as output: output.write(text)
    add(instructions, 'installation-instructions')
    provenance = {'schemaVersion': 1, 'purpose': 'owner-binary-delivery-after-specified-checks',
                  'repository': api.repository, 'source': run_record(origins['source'], origins['sourceJobs']),
                  'cross': run_record(origins['cross'], origins['crossJobs']),
                  'binaryArtifact': artifact_record(origins['binary']),
                  'otherPlatformBinaryArtifact': artifact_record(origins['otherBinary']),
                  'sourceArtifact': artifact_record(origins['sourceArtifact']),
                  'crossArtifact': artifact_record(origins['crossArtifact']),
                  'nativeArtifacts': [artifact_record(item) for item in origins['native']],
                  'binaryVerification': verified, 'sourceAndInstallerVerification': source_verified,
                  'originalSourceValidation': validation, 'originalCrossReport': cross_report,
                  'archiveStorage': plan, 'logs': logs, 'originalNoticeEntriesPreservedInTar': notices,
                  'binaryChecksPassed': {'sourceMatrix': True, 'sameMacOS26ArchiveInstalledOnMacOS27': True,
                                         'installedBinaryGUIOnMacOS27': True, 'guiOutsideDependencySandbox': True},
                  'limitations': LIMITATIONS, 'publicRelease': False, 'applicationLicenseAdded': False,
                  'files': [records[name] for name in sorted(records)]}
    path = payload / PROVENANCE; write_json(path, provenance); add(path, 'delivery-provenance')
    checksums = payload / CHECKSUMS
    with checksums.open('x') as output:
        for name in sorted(records): output.write(records[name]['sha256'] + '  ' + name + '\n')
    add(checksums, 'delivery-file-checksums')
    require(len(records) < 1000 and all(record['bytes'] < 2 * 1024 ** 3 for record in records.values()),
            'Delivery exceeds GitHub release asset limits.')
    return {'files': files, 'records': records, 'plan': plan, 'original': original, 'provenance': provenance}


def publish_draft(api, prepared, directory, source_id, commit, cross_id, cross_commit, sha):
    # This operation creates/completes a draft only. No public-publish operation exists.
    tag = 'delivery-' + commit[:12] + '-' + source_id + '-' + cross_id
    body = description(source_id, commit, cross_id, cross_commit, sha)
    matches = [item for item in api.listing('/releases') if item.get('tag_name') == tag]
    require(len(matches) <= 1, 'Ambiguous existing delivery drafts.')
    release = matches[0] if matches else api.json('/releases', 'POST', {
        'tag_name': tag, 'target_commitish': commit, 'name': 'PDF · pacote para instalação · ' + source_id,
        'body': body, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    evidence.validate_release(release, tag, commit, body)
    route = '/releases/' + str(release['id'])
    records, files = prepared['records'], prepared['files']
    assets = api.listing(route + '/assets', maximum=1000)
    names = [item.get('name') for item in assets]
    require(len(names) == len(set(names)) and set(names).issubset(records),
            'Existing draft has unexpected assets; nothing will be overwritten.')
    scratch = directory / 'asset-verification'; scratch.mkdir(mode=0o700)
    by_name = {item['name']: item for item in assets}
    for asset in assets:
        evidence.verify_asset_bytes(api, asset, records[asset['name']], scratch, MAX_ARCHIVE, LARGE_TIMEOUT)
    parts = {part['name']: part for part in prepared['plan']['parts']}
    for name, record in records.items():
        evidence.validate_release(api.json(route), tag, commit, body)
        if name in by_name:
            continue
        temporary = name not in files
        if temporary:
            require(name in parts, 'Missing local delivery asset.')
            path = scratch / name
            delivery_parts.materialize_part(prepared['original'], parts[name], path)
        else:
            path = files[name]
        try:
            require(evidence.local_hash(path, MAX_ARCHIVE)['sha256'] == record['sha256'],
                    'Local delivery asset changed before upload.')
            api.upload(tag, path, timeout=LARGE_TIMEOUT)
        finally:
            if temporary: path.unlink(missing_ok=True)
    evidence.validate_release(api.json(route), tag, commit, body)
    final = api.listing(route + '/assets', maximum=1000)
    require(len(final) == len(records) and {item.get('name') for item in final} == set(records),
            'Draft delivery inventory is incomplete.')
    for asset in final:
        evidence.verify_asset_bytes(api, asset, records[asset['name']], scratch, MAX_ARCHIVE, LARGE_TIMEOUT)
    evidence.validate_release(api.json(route), tag, commit, body)
    return {'releaseID': release['id'], 'tag': tag, 'draft': True, 'verifiedAssets': len(records),
            'archiveSHA256': sha, 'sourceRunID': int(source_id), 'crossRunID': int(cross_id),
            'binaryChecksPassed': True, 'limitations': LIMITATIONS}


def deliver(api, source_id, commit, expected_sha, cross_id, cross_commit, directory):
    origins = collect_origins(api, source_id, commit, expected_sha, cross_id, cross_commit)
    print('Authenticated source and cross-platform runs:', source_id, cross_id, flush=True)
    prepared = prepare(api, origins, directory)
    return publish_draft(api, prepared, directory, source_id, commit, cross_id, cross_commit, expected_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = deliver(evidence.GitHub(os.environ['GITHUB_REPOSITORY']), os.environ['PDF_SOURCE_RUN_ID'],
                         os.environ['PDF_SOURCE_COMMIT'], os.environ['PDF_EXPECTED_SHA'],
                         os.environ['PDF_CROSS_RUN_ID'], os.environ['PDF_CROSS_CONTROL_COMMIT'], args.directory)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('release_id=' + str(result['releaseID']) + '\nrelease_tag=' + result['tag']
                             + '\narchive_sha256=' + result['archiveSHA256'] + '\n')
        print(json.dumps(result, sort_keys=True))
    except evidence.EvidenceFailure as error:
        parser.exit(1, 'Binary delivery refused: ' + str(error) + '\n')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        parser.exit(1, 'Binary delivery could not complete. No release was published or existing asset overwritten.\n')


if __name__ == '__main__':
    main()
