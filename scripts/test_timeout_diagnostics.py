"""The optional macOS stack diagnostic must preserve timeout failure and cleanup."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

SCRIPT=Path(__file__).with_name('run-with-timeout.py')
spec=importlib.util.spec_from_file_location('deadline_diagnostics',SCRIPT)
deadline=importlib.util.module_from_spec(spec);spec.loader.exec_module(deadline)


class TimeoutDiagnosticTests(unittest.TestCase):
    def test_non_darwin_never_launches_sample(self):
        process=Mock(pid=12345);process.poll.return_value=None
        with patch.object(deadline.sys,'platform','linux'),patch.object(deadline.subprocess,'run') as sampler:
            deadline.sample_owned_process(process)
            sampler.assert_not_called()

    def test_sample_targets_only_owned_live_pid_and_inherits_logs(self):
        process=Mock(pid=12345);process.poll.return_value=None
        with patch.object(deadline.sys,'platform','darwin'),patch.object(deadline.subprocess,'run',return_value=Mock(returncode=0)) as sampler,redirect_stderr(io.StringIO()):
            deadline.sample_owned_process(process)
        sampler.assert_called_once_with(['/usr/bin/sample','12345','3','-mayDie','-file','/dev/stdout'],
            stdin=subprocess.DEVNULL,stdout=None,stderr=None,timeout=12,check=False)

    def test_nonzero_sampling_status_is_diagnostic_only(self):
        process=Mock(pid=12345);process.poll.return_value=None
        diagnostic=io.StringIO()
        with patch.object(deadline.sys,'platform','darwin'),patch.object(deadline.subprocess,'run',return_value=Mock(returncode=71)),redirect_stderr(diagnostic):
            self.assertIsNone(deadline.sample_owned_process(process))
        self.assertIn('returned 71',diagnostic.getvalue())
        self.assertIn('original timeout remains a failure',diagnostic.getvalue())

    def test_exited_child_is_never_sampled(self):
        process=Mock(pid=12345);process.poll.return_value=1
        with patch.object(deadline.sys,'platform','darwin'),patch.object(deadline.subprocess,'run') as sampler:
            deadline.sample_owned_process(process)
            sampler.assert_not_called()

    def test_sampling_failures_keep_exit_124_and_cleanup(self):
        for failure in (subprocess.TimeoutExpired('sample',12),FileNotFoundError('sample'),RuntimeError('unexpected')):
            with self.subTest(failure=type(failure).__name__):
                process=Mock(pid=12345)
                process.wait.side_effect=subprocess.TimeoutExpired('owned command',0.1)
                process.poll.side_effect=[None,0]
                with patch.object(deadline.sys,'platform','darwin'),patch.object(deadline.sys,'argv',
                        [str(SCRIPT),'--seconds','0.1','--sample-on-timeout','--','owned-command']), \
                        patch.object(deadline.subprocess,'Popen',return_value=process), \
                        patch.object(deadline.subprocess,'run',side_effect=failure), \
                        patch.object(deadline,'stop') as cleanup,redirect_stderr(io.StringIO()):
                    self.assertEqual(deadline.main(),124)
                    cleanup.assert_called_once_with(process)

    def test_timeout_without_opt_in_does_not_sample(self):
        process=Mock(pid=12345)
        process.wait.side_effect=subprocess.TimeoutExpired('owned command',0.1)
        process.poll.return_value=0
        with patch.object(deadline.sys,'argv',[str(SCRIPT),'--seconds','0.1','--','owned-command']), \
                patch.object(deadline.subprocess,'Popen',return_value=process), \
                patch.object(deadline,'sample_owned_process') as sampler, \
                patch.object(deadline,'stop') as cleanup,redirect_stderr(io.StringIO()):
            self.assertEqual(deadline.main(),124)
            sampler.assert_not_called()
            cleanup.assert_called_once_with(process)

    def test_normal_command_exit_is_preserved_with_opt_in(self):
        result=subprocess.run([sys.executable,str(SCRIPT),'--seconds','10','--sample-on-timeout','--',
            sys.executable,'-c','raise SystemExit(7)'],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,7)
        self.assertNotIn('Sampling',result.stderr)

if __name__=='__main__': unittest.main()
