#!/usr/bin/env python3
"""Retain incomplete native audit evidence in a draft, never approve a product."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess

import retain_evidence as evidence

require = evidence.require
CAPTURE = 'Capture native window preview'
ACCESSIBILITY = 'Validate all native previews and accessibility reports'
UPLOAD = 'Retain native preview artifact'
REQUIRED_STEPS = tuple(name for name in evidence.REQUIRED_STEPS if name not in (CAPTURE, ACCESSIBILITY))
MANIFEST = 'partial-evidence-provenance.json'


def moment(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z', value),
            'Missing canonical evidence timestamp.')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise evidence.EvidenceFailure('Invalid evidence timestamp.') from None


def inventory(value, field):
    items = value.get(field)
    require(type(value.get('total_count')) is int and isinstance(items, list)
            and 0 <= value['total_count'] <= 100 and len(items) == value['total_count'],
            'Incomplete evidence inventory.')
    return items


def validate_origin(run, jobs, artifacts, run_id, commit, repository):
    evidence.validate_inputs(run_id, commit, repository)
    require(run.get('id') == int(run_id) and run.get('status') == 'completed'
            and run.get('conclusion') == 'failure', 'Only a completed failed source run is eligible.')
    require(run.get('head_sha') == commit and run.get('path') == '.github/workflows/macos.yml',
            'Source commit or workflow mismatch.')
    repo, head = run.get('repository', {}), run.get('head_repository', {})
    require(repo.get('full_name') == head.get('full_name') == repository
            and evidence.positive_integer(repo.get('id')) and head.get('id') == repo['id'],
            'Only evidence from this same repository is eligible.')
    require(evidence.positive_integer(run.get('run_attempt')), 'Missing source attempt identity.')
    expected_jobs = {'native-application (' + runner + ')': runner for runner in evidence.RUNNERS}
    require(len(jobs) == 2 and {job.get('name') for job in jobs} == set(expected_jobs)
            and len({job.get('id') for job in jobs}) == 2, 'The exact two native platform jobs are required.')
    chosen_jobs, visual = {}, {}
    for job in jobs:
        require(evidence.positive_integer(job.get('id')) and job.get('run_id') == int(run_id)
                and job.get('run_attempt') == run['run_attempt'] and job.get('head_sha') == commit
                and job.get('status') == 'completed' and job.get('conclusion') in ('success', 'failure'),
                'Invalid native job identity or state.')
        require(moment(job.get('started_at')) < moment(job.get('completed_at')), 'Invalid native job interval.')
        steps = job.get('steps')
        require(isinstance(steps, list) and all(isinstance(step, dict) for step in steps), 'Missing native steps.')
        selected_steps = {}
        for name in (*REQUIRED_STEPS, CAPTURE, ACCESSIBILITY):
            matches = [step for step in steps if step.get('name') == name]
            require(len(matches) == 1 and matches[0].get('status') == 'completed',
                    'Missing, repeated or unfinished evidence gate: ' + name)
            selected_steps[name] = matches[0]
            if name in REQUIRED_STEPS:
                require(matches[0].get('conclusion') == 'success', 'Required native gate did not succeed: ' + name)
        capture, accessibility = selected_steps[CAPTURE]['conclusion'], selected_steps[ACCESSIBILITY]['conclusion']
        require((capture == 'success' and accessibility in ('success', 'failure'))
                or (capture == 'failure' and accessibility == 'skipped'),
                'Preview and accessibility states are inconsistent.')
        failed = capture == 'failure' or accessibility == 'failure'
        require(not failed or job['conclusion'] == 'failure', 'Visual failure contradicts job conclusion.')
        runner = expected_jobs[job['name']]
        chosen_jobs[runner] = job
        visual[runner] = {'capture': capture, 'accessibility': accessibility,
                          'artifactUpload': selected_steps[UPLOAD]['conclusion'],
                          'visualGateFailed': failed, 'imageCount': None, 'humanVisualReviewPerformed': False}
    require(any(item['visualGateFailed'] for item in visual.values()),
            'Partial retention requires an actual failed capture or visual gate.')
    chosen, missing = [], []
    for name in evidence.ARTIFACT_NAMES:
        matches = [item for item in artifacts if item.get('name') == name]
        runner = next(runner for runner in evidence.RUNNERS if name.endswith('-' + runner))
        is_preview = name == 'PDF-macOS-preview-' + runner
        if not matches:
            require(is_preview and visual[runner]['capture'] == 'failure',
                    'Required original artifact is missing: ' + name)
            missing.append(name)
            continue
        require(len(matches) == 1, 'Duplicate allowlisted artifact: ' + name)
        item = matches[0]
        require(evidence.positive_integer(item.get('id')) and item.get('expired') is False
                and evidence.positive_integer(item.get('size_in_bytes'))
                and item['size_in_bytes'] <= evidence.MAX_ARTIFACT
                and isinstance(item.get('digest'), str)
                and re.fullmatch('sha256:[0-9a-f]{64}', item['digest']) is not None,
                'Invalid, expired or oversized artifact: ' + name)
        origin = item.get('workflow_run', {})
        require(origin.get('id') == int(run_id) and origin.get('head_sha') == commit
                and origin.get('repository_id') == origin.get('head_repository_id') == repo['id'],
                'Foreign artifact origin: ' + name)
        job = chosen_jobs[runner]
        require(moment(job['started_at']) <= moment(item.get('created_at')) <= moment(job['completed_at']),
                'Artifact belongs to another job attempt: ' + name)
        chosen.append(item)
    require(len({item['id'] for item in chosen}) == len(chosen), 'Repeated artifact identity.')
    for runner, states in visual.items():
        name = 'PDF-macOS-preview-' + runner
        item = next((item for item in chosen if item['name'] == name), None)
        states.update(artifactName=name, artifactPresent=item is not None,
                      artifactID=item['id'] if item else None,
                      missingReason='capture-failed-without-artifact' if item is None else None)
    return chosen_jobs, chosen, missing, visual


def release_description(run_id, commit):
    return ('Evidências parciais de auditoria de uma execução reprovada. Rascunho privado ao proprietário, '
            'sem publicação pública, aprovação do aplicativo ou aprovação do instalador.\n\n'
            'Execução: ' + run_id + '\nCommit: `' + commit + '`\n\n'
            'Há falha real de captura ou validação visual. O manifesto registra os estados de cada etapa '
            'e os artefatos ausentes; imagens e relatórios ausentes não são recriados. '
            'Os ZIPs originais e o ZIP oficial de logs da tentativa permanecem sem extração ou execução. '
            'A retenção não comprova revisão humana das imagens. Não publicar nem substituir assets.\n')


def retain(api, run_id, commit, directory):
    base = '/actions/runs/' + run_id
    run = api.json(base)
    require(evidence.positive_integer(run.get('run_attempt')), 'Missing source attempt identity.')
    jobs = inventory(api.json(base + '/attempts/' + str(run['run_attempt']) + '/jobs?per_page=100'), 'jobs')
    artifacts = inventory(api.json(base + '/artifacts?per_page=100'), 'artifacts')
    chosen_jobs, selected, missing, visual = validate_origin(run, jobs, artifacts, run_id, commit, api.repository)
    print('Authenticated failed source run with partial visual evidence:', run_id, 'commit:', commit, flush=True)
    directory.mkdir(mode=0o700)
    files = []
    for item in selected:
        print('Retaining original artifact:', item['name'], 'ID:', item['id'], flush=True)
        file = directory / (item['name'] + '.zip')
        record = api.download('/actions/artifacts/' + str(item['id']) + '/zip', file, evidence.MAX_ARTIFACT,
                              expected_bytes=item['size_in_bytes'], expected_sha=item['digest'][7:])
        files.append(dict(record, kind='original-artifact-zip', artifactID=item['id'],
                          artifactName=item['name'], githubDigest=item['digest'], createdAt=item['created_at']))
    log_route = base + '/attempts/' + str(run['run_attempt']) + '/logs'
    file = directory / ('source-run-' + run_id + '-attempt-' + str(run['run_attempt']) + '-logs.zip')
    record = api.download(log_route, file, evidence.MAX_LOG)
    files.append(dict(record, kind='original-complete-attempt-logs-zip', sourceAPIPath=log_route,
                      sourceRunID=int(run_id), sourceRunAttempt=run['run_attempt'],
                      jobIDs=[chosen_jobs[runner]['id'] for runner in evidence.RUNNERS],
                      digestProvenance='calculated-from-original-download; no upstream digest supplied'))
    manifest = {'schemaVersion': 1, 'purpose': 'partial-original-audit-evidence-only',
                'repository': api.repository, 'sourceRunID': int(run_id), 'sourceCommit': commit,
                'sourceRunAttempt': run['run_attempt'], 'sourceWorkflow': run['path'], 'sourceConclusion': 'failure',
                'partialEvidence': True, 'productApproved': False, 'applicationApproved': False,
                'binaryDistributionApproved': False, 'archiveContentsExtractedOrExecuted': False,
                'expectedArtifactNames': list(evidence.ARTIFACT_NAMES), 'missingArtifactNames': missing,
                'artifactCounts': {'expected': 10, 'available': len(selected), 'missing': len(missing)},
                'previewArtifactCounts': {'expected': 2, 'available': 2 - len(missing), 'missing': len(missing)},
                'previewImageCount': None, 'humanVisualReviewPerformed': False,
                'jobs': [{'id': chosen_jobs[runner]['id'], 'runner': runner,
                          'conclusion': chosen_jobs[runner]['conclusion'],
                          'startedAt': chosen_jobs[runner]['started_at'], 'completedAt': chosen_jobs[runner]['completed_at'],
                          'requiredNativeGatesPassed': list(REQUIRED_STEPS), 'visualEvidence': visual[runner],
                          'steps': [{key: step.get(key) for key in ('name', 'status', 'conclusion')}
                                    for step in chosen_jobs[runner]['steps']]}
                         for runner in evidence.RUNNERS], 'files': files}
    with (directory / MANIFEST).open('x') as output:
        json.dump(manifest, output, indent=2, sort_keys=True); output.write('\n')
    tag = 'audit-partial-' + commit[:12] + '-' + run_id
    description = release_description(run_id, commit)
    matches = [release for release in api.listing('/releases') if release.get('tag_name') == tag]
    require(len(matches) <= 1, 'Ambiguous existing partial evidence releases.')
    release = matches[0] if matches else api.json('/releases', 'POST', {
        'tag_name': tag, 'target_commitish': commit, 'name': 'Auditoria parcial reprovada · ' + run_id,
        'body': description, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    evidence.validate_release(release, tag, commit, description)
    paths = [directory / item['name'] for item in files] + [directory / MANIFEST]
    assets = api.listing('/releases/' + str(release['id']) + '/assets', maximum=1000)
    names = [asset.get('name') for asset in assets]
    require(len(set(names)) == len(names) and set(names).issubset({path.name for path in paths}),
            'Existing draft contains duplicate or unexpected assets; nothing will be overwritten.')
    by_name = {asset['name']: asset for asset in assets}
    for path in paths:
        if path.name in by_name:
            evidence.compare_existing_asset(api, by_name[path.name], path, directory)
    for path in paths:
        evidence.validate_release(api.json('/releases/' + str(release['id'])), tag, commit, description)
        if path.name not in by_name:
            api.upload(tag, path)
    final = api.listing('/releases/' + str(release['id']) + '/assets', maximum=1000)
    require(len(final) == len(paths) and {asset.get('name') for asset in final} == {path.name for path in paths},
            'Partial evidence draft inventory is incomplete.')
    for asset in final:
        evidence.compare_existing_asset(api, asset, directory / asset['name'], directory)
    evidence.validate_release(api.json('/releases/' + str(release['id'])), tag, commit, description)
    return {'releaseID': release['id'], 'tag': tag, 'draft': True, 'sourceRunID': int(run_id),
            'sourceConclusion': 'failure', 'partialEvidence': True, 'productApproved': False,
            'missingArtifactNames': missing, 'verifiedAssets': len(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        run_id, commit = os.environ['PDF_SOURCE_RUN_ID'], os.environ['PDF_SOURCE_COMMIT']
        repository = os.environ['GITHUB_REPOSITORY']
        evidence.validate_inputs(run_id, commit, repository)
        result = retain(evidence.GitHub(repository), run_id, commit, args.directory)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('release_id=' + str(result['releaseID']) + '\n')
                output.write('release_tag=' + result['tag'] + '\n')
        print(json.dumps(result, sort_keys=True))
    except evidence.EvidenceFailure as error:
        parser.exit(1, 'Partial audit retention refused: ' + str(error) + '\n')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        parser.exit(1, 'Partial audit retention failed. No release was published or existing asset overwritten.\n')


if __name__ == '__main__':
    main()
