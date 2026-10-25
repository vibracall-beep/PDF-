import copy
import json
from pathlib import Path
import tempfile
import unittest
from compare_benchmarks import compare


class BenchmarkComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report = dict(schemaVersion=1, sourceSHA256='1' * 64, sourceBytes=100, pageCount=5,
                           processor='Apple M4', architecture='arm64', operatingSystem='Test OS',
                           activeProcessorCount=10, physicalMemoryBytes=16 * 1024**3,
                           graphicsDevice='Test GPU', virtualization='not established', fixture=None,
                           repetitions=3, methodology='same input warmed once',
                           metrics=[dict(id='open', detail='Abrir e resolver primeira e última página.', samplesMilliseconds=[10, 12, 14], error=None)])

    def tearDown(self):
        self.temporary.cleanup()

    def run_comparison(self, after):
        a, b = self.root / 'a.json', self.root / 'b.json'
        a.write_text(json.dumps(self.report)); b.write_text(json.dumps(after))
        return compare(a, b)

    def test_rejects_hardware_and_source_changes(self):
        for key, value in [('processor', 'Apple M5'), ('sourceSHA256', '2' * 64), ('repetitions', 2), ('methodology', 'cold')]:
            after = copy.deepcopy(self.report); after[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_comparison(after)

    def test_compares_actual_medians_and_retains_samples(self):
        after = copy.deepcopy(self.report); after['metrics'][0]['samplesMilliseconds'] = [6, 7, 5]
        result = self.run_comparison(after)
        self.assertEqual(result['results'][0]['change_percent'], -50)
        self.assertEqual(result['results'][0]['baseline_samples_ms'], [10, 12, 14])
        self.assertNotEqual(result['baseline_report_sha256'], result['candidate_report_sha256'])

    def test_zero_negative_nonfinite_missing_and_boolean_samples_fail(self):
        for samples in ([0, 1, 2], [True, 1, 2], [float('nan'), 1, 2], [-1, 1, 2], [1, 2]):
            after = copy.deepcopy(self.report); after['metrics'][0]['samplesMilliseconds'] = samples
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                self.run_comparison(after)

    def test_failed_or_duplicate_operations_are_not_speedups(self):
        after = copy.deepcopy(self.report); after['metrics'][0]['error'] = 'Failed'
        with self.assertRaises(ValueError): self.run_comparison(after)
        after = copy.deepcopy(self.report); after['metrics'].append(copy.deepcopy(after['metrics'][0]))
        with self.assertRaises(ValueError): self.run_comparison(after)

    def test_operation_scope_change_is_not_a_speedup(self):
        after = copy.deepcopy(self.report)
        after['metrics'][0]['detail'] = 'Abrir somente o cabeçalho sem resolver páginas.'
        with self.assertRaisesRegex(ValueError, 'alcance'): self.run_comparison(after)
        del after['metrics'][0]['detail']
        with self.assertRaises(ValueError): self.run_comparison(after)

    def test_thermal_and_power_conditions_must_match_and_remain_stable(self):
        self.report.update(thermalLevelAtStart=0, thermalLevelAtEnd=0,
                           lowPowerMode=False, lowPowerModeAtStart=False, lowPowerModeAtEnd=False)
        for change in [dict(thermalLevelAtStart=1, thermalLevelAtEnd=1),
                       dict(thermalLevelAtEnd=1), dict(lowPowerModeAtEnd=True),
                       dict(lowPowerMode=True, lowPowerModeAtStart=True, lowPowerModeAtEnd=True)]:
            after = copy.deepcopy(self.report); after.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_comparison(after)
        self.assertEqual(len(self.run_comparison(copy.deepcopy(self.report))['results']), 1)

    def test_invalid_or_partial_condition_evidence_is_refused(self):
        for change in [dict(thermalLevelAtStart=0), dict(thermalLevelAtStart=True, thermalLevelAtEnd=True),
                       dict(thermalLevelAtStart=4, thermalLevelAtEnd=4), dict(lowPowerMode='false'),
                       dict(lowPowerModeAtEnd=False), dict(lowPowerModeAtStart=0, lowPowerModeAtEnd=0)]:
            after = copy.deepcopy(self.report); after.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_comparison(after)
