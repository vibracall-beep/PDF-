#!/usr/bin/env python3
"""Extract and verify App Intents metadata using Apple's installed build SDK."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import tempfile

EXPECTED = {'OpenPDFIntent', 'RunSavedPDFWorkflowIntent'}


def read_json(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 ** 2:
            raise ValueError('Metadados de Atalhos não são um JSON regular dentro do limite.')
        data = stream.read(8 * 1024 ** 2 + 1)
        if len(data) != info.st_size:
            raise ValueError('Metadados de Atalhos mudaram durante a leitura.')
        return json.loads(data)


def contains_value(value, expected):
    if isinstance(value, dict):
        return any(contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(contains_value(item, expected) for item in value)
    return value == expected


def verify(resources):
    metadata = Path(resources) / 'Metadata.appintents'
    report = read_json(metadata / 'extract.actionsdata')
    version = read_json(metadata / 'version.json')
    if not isinstance(report, dict) or not isinstance(version, dict):
        raise ValueError('Metadados App Intents devem conter objetos JSON.')
    if report.get('version') != 1 or not isinstance(version.get('version'), str) or not version.get('toolsVersion'):
        raise ValueError('Versão de metadados App Intents ausente ou não reconhecida.')
    actions = report.get('actions')
    if not isinstance(actions, dict) or not EXPECTED <= actions.keys():
        raise ValueError('As duas ações obrigatórias não foram extraídas pelo SDK.')
    for name in EXPECTED:
        action = actions[name]
        if not isinstance(action, dict):
            raise ValueError('Definição de ação inválida.')
        if (action.get('identifier') != name or action.get('fullyQualifiedTypeName') != 'PDF.' + name
                or action.get('openAppWhenRun') is not True or action.get('isDiscoverable') is not True):
            raise ValueError('Ação não está publicamente disponível como esperado: ' + name)
        parameters = {item.get('name'): item for item in action.get('parameters', [])}
        document = parameters.get('document', {})
        if (document.get('isOptional') is not False
                or document.get('valueType') != {'intents': {'wrapper': {'typeIdentifier': 12}}}
                or not contains_value(document.get('typeSpecificMetadata'), 'com.adobe.pdf')):
            raise ValueError('A ação não exige um documento PDF: ' + name)
        if name == 'RunSavedPDFWorkflowIntent':
            if (parameters.get('workflow', {}).get('isOptional') is not False
                    or parameters.get('workflow', {}).get('valueType') != {'entity': {'wrapper': {'typeName': 'PDFWorkflowEntity'}}}):
                raise ValueError('A ação de fluxo não foi vinculada à entidade de fluxos salvos.')
    if 'PDFAppShortcuts' not in report.get('autoShortcutProviderMangledName', ''):
        raise ValueError('O provider AppShortcuts não foi extraído.')
    shortcuts = report.get('autoShortcuts')
    if not isinstance(shortcuts, list) or {item.get('actionIdentifier') for item in shortcuts} != EXPECTED:
        raise ValueError('Os dois atalhos automáticos obrigatórios estão ausentes.')
    for shortcut in shortcuts:
        phrases = shortcut.get('phraseTemplates')
        if not isinstance(phrases, list) or not phrases or not all('${applicationName}' in item.get('key', '') for item in phrases):
            raise ValueError('Atalho sem frase de invocação válida.')
    entity = report.get('entities', {}).get('PDFWorkflowEntity', {})
    query = report.get('queries', {}).get('PDFWorkflowQuery', {})
    if (entity.get('defaultQueryIdentifier') != 'PDF.PDFWorkflowQuery'
            or query.get('entityType') != 'PDFWorkflowEntity' or query.get('defaultQueryForEntity') is not True):
        raise ValueError('A entidade de fluxos não possui a consulta de descoberta obrigatória.')
    return {'actions': sorted(EXPECTED), 'provider': 'PDFAppShortcuts',
            'entity': 'PDFWorkflowEntity', 'metadataVersion': version['version'], 'toolsVersion': version['toolsVersion']}


def extract(source_root, resources):
    source_root = Path(source_root).resolve(strict=True)
    resources = Path(resources).resolve(strict=True)
    target = resources / 'Metadata.appintents'
    if os.path.lexists(target):
        raise ValueError('Os metadados já existem; extração exige um bundle novo.')
    def output(*args):
        return subprocess.check_output(args, text=True).strip()
    sdk = output('xcrun', '--sdk', 'macosx', '--show-sdk-path')
    compiler = output('xcrun', '--find', 'swiftc')
    toolchain = Path(compiler).parent.parent.parent
    version = output('xcodebuild', '-version').split('Build version ', 1)[1].strip()
    sources = sorted((source_root / 'Sources/PDF').glob('*.swift'))
    if not sources or any('\n' in str(path) for path in sources):
        raise ValueError('Lista de fontes Swift inválida.')
    with tempfile.TemporaryDirectory(prefix='PDF-AppIntents-') as temporary:
        temporary = Path(temporary)
        protocols = temporary / 'protocols.json'
        protocols.write_text(json.dumps(['AppIntent', 'AppEntity', 'EntityQuery', 'AppShortcutsProvider', 'AppEnum', 'AppIntentsPackage']))
        source_list = temporary / 'sources.txt'; source_list.write_text(''.join(str(path)+'\n' for path in sources))
        constants = temporary / 'PDF.swiftconstvalues'
        # Ask this installed SDK's driver for the frontend configuration,
        # including SwiftUIMacros plugin paths. Run it as one complete module:
        # per-primary-file driver jobs otherwise overwrite a shared const file.
        driver = subprocess.check_output([compiler, '-driver-print-jobs', '-typecheck', '-parse-as-library',
            '-swift-version', '5', '-module-name', 'PDF', '-target', 'arm64-apple-macosx26.0', '-sdk', sdk,
            *map(str, sources)], text=True, timeout=30)
        jobs = [shlex.split(line) for line in driver.splitlines() if line.strip()]
        frontend = next((job for job in jobs if '-frontend' in job and '-typecheck' in job), None)
        if frontend is None or not set(map(str, sources)) <= set(frontend):
            raise ValueError('O driver não forneceu a invocação completa do módulo Swift.')
        frontend = [argument for argument in frontend if argument != '-primary-file']
        frontend += ['-emit-const-values-path', str(constants), '-const-gather-protocols-file', str(protocols)]
        subprocess.run(frontend, check=True, timeout=300)
        if not constants.is_file() or constants.stat().st_size == 0:
            raise ValueError('O compilador não produziu constantes App Intents.')
        constants_list = temporary / 'constants.txt'; constants_list.write_text(str(constants)+'\n')
        extracted = temporary / 'extracted'; extracted.mkdir()
        subprocess.run(['xcrun', 'appintentsmetadataprocessor', '--output', str(extracted),
            '--toolchain-dir', str(toolchain), '--module-name', 'PDF', '--sdk-root', sdk,
            '--xcode-version', version, '--platform-family', 'macOS', '--deployment-target', '26.0',
            '--target-triple', 'arm64-apple-macosx26.0', '--source-file-list', str(source_list),
            '--swift-const-vals-list', str(constants_list), '--deployment-aware-processing'], check=True, timeout=120)
        report = verify(extracted)
        shutil.copytree(extracted / 'Metadata.appintents', target)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('extract', 'verify'))
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        report = extract(args.source_root, args.resources) if args.operation == 'extract' else verify(args.resources)
        print('App Intents metadata:', json.dumps(report, ensure_ascii=False))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Metadados de Atalhos recusados: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
