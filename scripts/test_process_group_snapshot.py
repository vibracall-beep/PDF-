"""Real Apple-SDK witness controls run before the expensive application build."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
import owned_process


@unittest.skipUnless(sys.platform == 'darwin', 'The Apple SDK and actual macOS process table are required.')
class NativeProcessGroupSnapshotTests(unittest.TestCase):
    def test_real_consensus_rejects_live_descendant_and_accepts_only_zombies_in_both_profiles(self):
        spec = importlib.util.spec_from_file_location('process_group_diagnosis', ROOT/'diagnostics/process_ownership_diagnostics.py')
        diagnostic=importlib.util.module_from_spec(spec); spec.loader.exec_module(diagnostic)
        with tempfile.TemporaryDirectory(prefix='PDF process group witness ') as temporary:
            directory=Path(temporary); helper=directory/'pdf-process-group-check'; control=directory/'control'
            for source, output in [(ROOT/'scripts/ProcessGroupSnapshot.c',helper),(ROOT/'diagnostics/ProcessOwnershipProbe.c',control)]:
                subprocess.run(['/usr/bin/xcrun','clang','-arch','arm64','-mmacosx-version-min=26.0',
                    '-std=c11','-Wall','-Wextra','-Werror','-O2',str(source),'-lproc','-o',str(output)],
                    check=True,timeout=60)
            profile=diagnostic.production_profile()
            original_ps=diagnostic.external_ps
            for sandbox in (None,profile):
                for mode in ('solo','live'):
                    with self.subTest(sandbox=sandbox is not None,mode=mode):
                        witnesses=[]
                        def consult(group):
                            prefix=[] if sandbox is None else ['/usr/bin/sandbox-exec','-p',sandbox]
                            result=subprocess.run([*prefix,str(helper),str(group)],capture_output=True,check=True,timeout=5)
                            self.assertEqual(result.stderr,b'')
                            self.assertEqual(owned_process._validate_group_snapshot(result.stdout,group),mode=='solo')
                            snapshot=json.loads(result.stdout); external=original_ps(group)
                            self.assertTrue(external['complete'])
                            self.assertEqual({item['pid'] for item in snapshot['members']},
                                             {item['pid'] for item in external['members']})
                            witnesses.append(snapshot)
                            return external
                        with mock.patch.object(diagnostic,'external_ps',side_effect=consult):
                            result=diagnostic.case(control,mode,sandbox,directory/(str(sandbox is not None)+'-'+mode+'.json'))
                        self.assertTrue(result['measurementComplete'])
                        self.assertTrue(result['candidateControlMatched'])
                        self.assertEqual(len(witnesses),1)


if __name__ == '__main__': unittest.main()
