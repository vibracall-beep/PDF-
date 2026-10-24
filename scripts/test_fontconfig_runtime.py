"""Keep font defaults public and cache writes outside the signed app."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from package_binary import FONTCONFIG_DEFAULTS, configure_private_fontconfig


class PrivateFontConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-fontconfig-')
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = self.root / 'runtime'
        self.defaults = self.runtime / 'vendor/fontconfig/share/fontconfig/conf.avail'
        self.defaults.mkdir(parents=True)
        for name in FONTCONFIG_DEFAULTS:
            (self.defaults / name).write_text('<fontconfig><description>public fixture</description></fontconfig>')
        # The official 2.18.3 rule uses xsi:nil without an xmlns declaration;
        # fontconfig's namespace-disabled Expat accepts this configuration.
        (self.defaults / '48-guessfamily.conf').write_text('<fontconfig><match><test><const xsi:nil="true"/></test></match></fontconfig>')
        dtd = self.runtime / 'vendor/fontconfig/share/xml/fontconfig/fonts.dtd'
        dtd.parent.mkdir(parents=True); dtd.write_text('<!ELEMENT fontconfig ANY>')

    def test_only_public_defaults_are_selected_and_cache_is_outside_bundle(self):
        private = '<fontconfig><include>/private/host/fonts.conf</include></fontconfig>'
        for name in ('50-user.conf', '51-local.conf', '99-private.conf'):
            (self.defaults / name).write_text(private)
        result = configure_private_fontconfig(self.runtime)
        self.assertEqual({path.name for path in (result / 'conf.d').iterdir()}, set(FONTCONFIG_DEFAULTS))
        tree = ET.parse(result / 'fonts.conf')
        self.assertEqual([node.text for node in tree.findall('dir')],
                         ['/System/Library/Fonts', '/Library/Fonts', '~/Library/Fonts'])
        self.assertEqual([node.text for node in tree.findall('cachedir')], ['~/Library/Caches/PDF/fontconfig'])
        self.assertEqual([node.text for node in tree.findall('include')], ['conf.d'])
        self.assertNotIn('/opt/homebrew', (result / 'fonts.conf').read_text())

    def test_changed_public_rule_cannot_import_host_configuration(self):
        (self.defaults / FONTCONFIG_DEFAULTS[0]).write_text(
            '<fontconfig><include>/opt/homebrew/etc/private.conf</include></fontconfig>')
        with self.assertRaisesRegex(ValueError, 'configuração externa'):
            configure_private_fontconfig(self.runtime)

    def test_symlinked_public_rule_is_refused(self):
        private = self.root / 'private.conf'; private.write_text('private configuration')
        rule = self.defaults / FONTCONFIG_DEFAULTS[0]; rule.unlink(); rule.symlink_to(private)
        with self.assertRaises(OSError): configure_private_fontconfig(self.runtime)
        self.assertEqual(private.read_text(), 'private configuration')


if __name__ == '__main__':
    unittest.main()
