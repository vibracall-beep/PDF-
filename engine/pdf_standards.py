"""Independent veraPDF PDF/A and PDF/UA validation; never changes the input."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

VERAPDF_VERSION = '1.30.3'
VERAPDF_SHA256 = '4c8acbaeb16405456c8d6d76deac8cf40d94618cb4e33aedf44e51ee1b68be91'
VERAPDF_URL = 'https://repo.maven.apache.org/maven2/org/verapdf/apps/cli/1.30.3/cli-1.30.3.jar'


def validator_paths():
    configured = os.environ.get('PDF_VERAPDF_JAR')
    if configured:
        jar = Path(configured).expanduser()
    else:
        import sys
        jar = Path(sys.prefix)/'share/verapdf'/f'cli-{VERAPDF_VERSION}.jar'
    if not jar.is_file():
        raise RuntimeError('veraPDF não está instalado. Execute o instalador completo para validar PDF/A e PDF/UA.')
    with jar.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != VERAPDF_SHA256:
        raise RuntimeError('A integridade do validador veraPDF não confere. Reinstale o componente oficial.')
    java = os.environ.get('PDF_JAVA') or shutil.which('java')
    if not java:
        raise RuntimeError('Java 21 não está disponível. Execute o instalador completo.')
    return str(java), str(jar)


def accessibility_preflight(path):
    import fitz
    with fitz.open(path) as document:
        if document.needs_pass or (document.metadata or {}).get('encryption'):
            raise ValueError('PDF/A e PDF/UA não permitem criptografia. Desbloqueie uma cópia antes de validar.')
        catalog = document.pdf_catalog()
        tree_type, tree_value = document.xref_get_key(catalog, 'StructTreeRoot')
        marked_type, marked_value = document.xref_get_key(catalog, 'MarkInfo/Marked')
        lang_type, lang_value = document.xref_get_key(catalog, 'Lang')
        has_tree = tree_type in ('xref','dict') and tree_value not in ('null','<<>>','<< >>')
        return dict(has_structure_tree=has_tree, marked=marked_type=='bool' and marked_value=='true',
                    document_language=lang_value if lang_type=='string' else None,
                    pages=len(document), manual_review_required=True,
                    checks_requiring_human_review=[
                        'Ordem de leitura e hierarquia semântica dos títulos.',
                        'Texto alternativo significativo para imagens e gráficos.',
                        'Associação correta de cabeçalhos em tabelas e nomes de campos.',
                        'Navegação com teclado, contraste e teste com leitor de tela.',
                    ])


def parse_report(xml, standard, flavour, preflight):
    from lxml import etree
    if len(xml.encode('utf-8')) > 16*1024*1024:
        raise RuntimeError('O relatório veraPDF excede o limite de 16 MB.')
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(xml.encode('utf-8'), parser=parser)
    if root.tag != 'report' or root.getroottree().docinfo.doctype:
        raise RuntimeError('Resposta inesperada do veraPDF.')
    reports = root.findall('./jobs/job/validationReport')
    batch = root.find('batchSummary')
    if len(reports) != 1 or batch is None or any(int(batch.get(key,'0')) for key in ('failedToParse','encrypted','outOfMemory','veraExceptions')):
        raise RuntimeError('veraPDF não conseguiu validar este documento. Não foi emitida uma declaração de conformidade.')
    validation = reports[0]
    if validation.get('jobEndStatus') != 'normal' or validation.get('isCompliant') not in ('true','false'):
        raise RuntimeError('A validação não terminou normalmente.')
    details = validation.find('details')
    if details is None:
        raise RuntimeError('O validador não retornou contagens de regras.')
    counts = {key: int(details.get(key,'0')) for key in ('passedRules','failedRules','passedChecks','failedChecks')}
    if counts['passedRules'] + counts['failedRules'] == 0:
        raise RuntimeError('O validador não executou regras de conformidade.')
    findings = []
    for rule in details.findall('rule'):
        if rule.get('status') != 'failed': continue
        checks = [{'context': check.findtext('context',''), 'message': check.findtext('errorMessage','')}
                  for check in rule.findall('check')]
        findings.append(dict(severity='error', rule=f"{rule.get('specification')} / {rule.get('clause')} / {rule.get('testNumber')}",
            specification=rule.get('specification'), clause=rule.get('clause'), test_number=rule.get('testNumber'),
            message=rule.findtext('description',''), failed_checks=int(rule.get('failedChecks','0')), checks=checks))
    compliant = validation.get('isCompliant') == 'true' and counts['failedRules'] == counts['failedChecks'] == 0
    if standard == 'pdfua' and not (preflight['has_structure_tree'] and preflight['marked']):
        compliant = False
        findings.append(dict(severity='error', rule='accessibility-structure-preflight',
            message='O documento precisa de uma árvore estrutural de tags e MarkInfo/Marked=true. Metadados isolados não tornam um PDF acessível.'))
    if standard == 'pdfua':
        summary = ('Regras automáticas de PDF/UA atendidas; a revisão humana de acessibilidade continua obrigatória.' if compliant
                   else 'O documento não atende às regras automáticas de PDF/UA. Consulte as falhas e o roteiro de acessibilidade.')
    else:
        summary = 'Conformidade PDF/A confirmada pelo veraPDF para o perfil escolhido.' if compliant else 'O documento não está conforme o perfil PDF/A escolhido.'
    return dict(schema_version=1, kind='standards-validation', standard=standard, flavour=flavour,
        checked_at=dt.datetime.now(dt.timezone.utc).isoformat(), validator=dict(name='veraPDF',version=VERAPDF_VERSION,sha256=VERAPDF_SHA256),
        profile=validation.get('profileName'), compliant=compliant, summary=summary, counts=counts,
        findings=findings, accessibility_preflight=preflight if standard=='pdfua' else None,
        manual_review_required=standard=='pdfua', accessibility_certified=False,
        network_access=False, displayed_checks_per_rule_limit=20, validator_xml=xml,
        limitations=['O resultado vale somente para os bytes e perfil examinados.',
                     'Nenhuma tag, metadado ou estrutura foi criada ou corrigida automaticamente.',
                     'PDF/UA exige revisão humana de significado, ordem de leitura, textos alternativos e interação.'])


def validate_pdf(input_path, output_path, options, standard='pdfa'):
    from pdf_engine import _external
    if standard not in ('pdfa','pdfua'):
        raise ValueError('Selecione PDF/A ou PDF/UA.')
    flavour = options.get('flavour', '2b' if standard=='pdfa' else 'ua1')
    allowed = ('1a','1b','2a','2b','2u','3a','3b','3u','4','4f','4e') if standard=='pdfa' else ('ua1','ua2')
    if flavour not in allowed:
        raise ValueError('Perfil de conformidade inválido para a família selecionada.')
    java, jar = validator_paths()
    # The digest, preflight and independent validator must inspect identical bytes,
    # even if another application saves the original while validation runs.
    with tempfile.TemporaryDirectory(prefix='pdf-standards-') as temporary:
        snapshot = Path(temporary)/'document.pdf'
        shutil.copyfile(input_path, snapshot)
        preflight = accessibility_preflight(snapshot)
        result = _external([java,'-Xmx512m','-Djava.awt.headless=true','-jar',jar,
            '--format','xml','--flavour',flavour,'--maxfailuresdisplayed','20',str(snapshot)],
            timeout=180, allowed_returncodes=(0,1))
        report = parse_report(result.stdout, standard, flavour, preflight)
        report['input_sha256'] = _digest_file(snapshot)
    report['file'] = Path(input_path).name
    with Path(output_path).open('x',encoding='utf-8') as destination:
        json.dump(report,destination,ensure_ascii=False,indent=2)
    return report


def _digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
