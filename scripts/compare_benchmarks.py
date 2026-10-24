#!/usr/bin/env python3
"""Compare measured benchmark reports only when the experiment is comparable.

This does not drive or certify competitor applications. It compares reports
produced with the same machine, input bytes and measurement methodology.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median


def load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024**2:
        raise ValueError('O relatório precisa ser um arquivo regular de até 8 MiB.')
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or type(value.get('schemaVersion')) is not int or value['schemaVersion'] != 1:
        raise ValueError('Formato de benchmark incompatível.')
    if not re.fullmatch(r'[a-f0-9]{64}', value.get('sourceSHA256', '')):
        raise ValueError('O benchmark não identifica os bytes da origem.')
    repetitions = value.get('repetitions')
    if type(repetitions) is not int or not 2 <= repetitions <= 100:
        raise ValueError('Exija ao menos duas medições, sem contar aquecimento.')
    metrics = value.get('metrics')
    if not isinstance(metrics, list) or not metrics:
        raise ValueError('Não há medições.')
    identifiers = set()
    for metric in metrics:
        if not isinstance(metric, dict) or not isinstance(metric.get('id'), str) or not metric['id'] or metric['id'] in identifiers:
            raise ValueError('Operação ausente ou repetida no relatório.')
        identifiers.add(metric['id'])
        samples = metric.get('samplesMilliseconds')
        if metric.get('error') or not isinstance(samples, list) or len(samples) != repetitions or any(type(x) not in (float, int) or not math.isfinite(x) or x <= 0 for x in samples):
            raise ValueError('Uma operação falhou ou não contém amostras positivas completas.')
    return value, hashlib.sha256(raw).hexdigest()


def compare(baseline, candidate):
    first, first_hash = load(baseline)
    second, second_hash = load(candidate)
    required = ('sourceSHA256', 'sourceBytes', 'pageCount', 'processor', 'architecture',
                'operatingSystem', 'activeProcessorCount', 'physicalMemoryBytes',
                'graphicsDevice', 'virtualization', 'fixture', 'repetitions', 'methodology')
    for key in required:
        if key not in first or key not in second or first[key] != second[key]:
            raise ValueError('Comparação recusada: entradas, hardware ou método diferem em ' + key + '.')
    for key in ('resourcePolicy', 'lowPowerMode'):
        if first.get(key) != second.get(key):
            raise ValueError('Comparação recusada: a política de processamento difere em ' + key + '.')
    initial = {item['id']: item for item in first['metrics']}
    if set(initial) != {item['id'] for item in second['metrics']}:
        raise ValueError('As operações medidas são diferentes.')
    results = []
    for current in second['metrics']:
        previous = initial[current['id']]
        before, after = median(previous['samplesMilliseconds']), median(current['samplesMilliseconds'])
        different_backend = previous.get('ocrSamples') != current.get('ocrSamples')
        results.append(dict(operation=current['id'], baseline_median_ms=before, candidate_median_ms=after,
                            change_percent=(after / before - 1) * 100,
                            baseline_samples_ms=previous['samplesMilliseconds'], candidate_samples_ms=current['samplesMilliseconds'],
                            backend_evidence_changed=different_backend))
    return dict(schema_version=1, baseline_report_sha256=first_hash, candidate_report_sha256=second_hash,
                source_sha256=first['sourceSHA256'], processor=first['processor'], results=results,
                scope='Comparação descritiva de amostras. Não comprova significância estatística, qualidade equivalente, consumo de energia ou superioridade de mercado.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline'); parser.add_argument('candidate'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = compare(args.baseline, args.candidate)
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print('Comparação salva; amostras originais e procedência preservadas.')


if __name__ == '__main__':
    main()
