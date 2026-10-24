#!/usr/bin/env python3
"""Validate actual SDK26 extracted schema and reject incomplete discovery."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from app_intents_metadata import verify

# JSON content printed by appintentsmetadataprocessor in Actions40064321346,
# macOS26 job, SHA e35b2680022f145bf086fa65ffccfab536ea31db. Not a binary copy
# of the downloadable artifact: this fixture is parsed from that public log.
FIXTURE = Path(__file__).parent / 'fixtures/app-intents-sdk26.json'


class AppIntentsMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.metadata = self.root / 'Metadata.appintents'; self.metadata.mkdir()
        self.report = json.loads(FIXTURE.read_text())
        self.path = self.metadata / 'extract.actionsdata'
        (self.metadata / 'version.json').write_text(json.dumps({'version':'3.0','toolsVersion':'17F113'}))
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    def save(self):
        self.path.write_text(json.dumps(self.report))

    def test_actual_sdk26_metadata_has_both_actions_provider_entity_and_query(self):
        self.assertEqual(verify(self.root)['actions'], ['OpenPDFIntent', 'RunSavedPDFWorkflowIntent'])

    def test_zero_exit_without_output_cannot_pass_verification(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError): verify(self.root)

    def test_incomplete_action_or_hidden_action_cannot_pass(self):
        self.report['actions']['OpenPDFIntent']['isDiscoverable'] = False
        self.save()
        with self.assertRaises(ValueError): verify(self.root)
        del self.report['actions']['OpenPDFIntent']
        self.save()
        with self.assertRaises(ValueError): verify(self.root)

    def test_provider_or_phrase_absence_is_rejected(self):
        self.report['autoShortcutProviderMangledName'] = ''
        self.save()
        with self.assertRaises(ValueError): verify(self.root)
        self.report = json.loads(FIXTURE.read_text())
        self.report['autoShortcuts'][0]['phraseTemplates'] = []
        self.save()
        with self.assertRaises(ValueError): verify(self.root)

    def test_workflow_entity_must_have_a_real_discovery_query(self):
        del self.report['queries']['PDFWorkflowQuery']
        self.save()
        with self.assertRaises(ValueError): verify(self.root)
        self.report = json.loads(FIXTURE.read_text())
        self.report['actions']['RunSavedPDFWorkflowIntent']['parameters'][1]['isOptional'] = True
        self.save()
        with self.assertRaises(ValueError): verify(self.root)

    def test_document_parameter_must_restrict_input_to_pdf(self):
        for metadata in ([], ['com.adobe.pdf.invalid']):
            self.report['actions']['OpenPDFIntent']['parameters'][0]['typeSpecificMetadata'] = metadata
            self.save()
            with self.assertRaises(ValueError): verify(self.root)
        self.report = json.loads(FIXTURE.read_text())
        self.report['actions']['OpenPDFIntent']['parameters'][0]['valueType'] = {'string': {}}
        self.save()
        with self.assertRaises(ValueError): verify(self.root)

    def test_symlink_and_fifo_metadata_are_rejected(self):
        self.path.unlink(); self.path.symlink_to(FIXTURE)
        with self.assertRaises(OSError): verify(self.root)
        self.path.unlink(); os.mkfifo(self.path)
        with self.assertRaises(ValueError): verify(self.root)


if __name__ == '__main__':
    unittest.main()
