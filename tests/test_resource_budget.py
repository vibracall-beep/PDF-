import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from resource_budget import worker_count


class ResourceBudgetTests(unittest.TestCase):
    def test_machine_limits_override_requested_parallelism(self):
        self.assertEqual(worker_count({'PDF_WORKERS': '999'}, 32, 4 * 1024**3), 2)
        self.assertEqual(worker_count({'PDF_WORKERS': '8'}, 1, 128 * 1024**3), 1)

    def test_invalid_and_zero_requests_remain_bounded(self):
        for value in ('0', '-4', 'nan', '1.5', '', None):
            with self.subTest(value=value):
                self.assertEqual(worker_count({'PDF_WORKERS': value}, 12, 32 * 1024**3), 1)

    def test_default_keeps_room_for_interaction(self):
        self.assertEqual(worker_count({}, 4, 32 * 1024**3), 3)
        self.assertEqual(worker_count({}, 16, 32 * 1024**3), 4)
