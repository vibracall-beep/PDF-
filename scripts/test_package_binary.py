"""Exercise real certificate and symlink relocation without a macOS build."""
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest

from package_binary import register_public_ca, relocate_links


class BinaryCertificateRelocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-binary-ca-')
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.prefix = self.root / 'host-prefix'
        self.original = self.prefix / 'Cellar/openssl/fixture'; self.original.mkdir(parents=True)
        self.runtime = self.root / 'private runtime'
        self.copied = self.runtime / 'vendor/openssl'; self.copied.mkdir(parents=True)
        self.public = self.runtime / 'vendor/ca-certificates/share/ca-certificates/cacert.pem'
        self.public.parent.mkdir(parents=True)
        subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(self.root / 'synthetic-private.key'), '-out', str(self.public),
                        '-subj', '/CN=PDF synthetic public CA', '-days', '1'],
                       check=True, capture_output=True, timeout=15)
        self.public_bytes = self.public.read_bytes()
        self.global_ca = self.prefix / 'etc/ca-certificates/cert.pem'; self.global_ca.parent.mkdir(parents=True)
        self.local_policy = self.root / 'private-host-policy.pem'
        self.local_policy.write_bytes(b'PRIVATE HOST POLICY MUST NOT BE COPIED')
        self.global_ca.symlink_to(self.local_policy)
        self.maps = {self.original: self.copied}

    def test_global_ca_reference_maps_to_public_store_without_copying_host_trust(self):
        (self.original / 'cert.pem').symlink_to(self.global_ca)
        (self.copied / 'cert.pem').symlink_to(self.global_ca)
        register_public_ca(self.runtime, self.maps, self.prefix)
        relocate_links(self.original, self.copied, self.maps)
        link = self.copied / 'cert.pem'
        self.assertFalse(os.path.isabs(os.readlink(link)))
        self.assertEqual(link.resolve(), self.public)
        self.assertTrue(link.samefile(self.public))
        self.assertEqual(link.read_bytes(), self.public_bytes)
        self.assertEqual(self.local_policy.read_bytes(), b'PRIVATE HOST POLICY MUST NOT BE COPIED')
        self.assertFalse(any(path.name == self.local_policy.name for path in self.runtime.rglob('*')))

    def test_other_external_configuration_is_still_rejected(self):
        (self.original / 'other.cnf').symlink_to(self.local_policy)
        (self.copied / 'other.cnf').symlink_to(self.local_policy)
        register_public_ca(self.runtime, self.maps, self.prefix)
        with self.assertRaisesRegex(ValueError, 'externa não empacotada'):
            relocate_links(self.original, self.copied, self.maps)
        self.assertEqual(self.local_policy.read_bytes(), b'PRIVATE HOST POLICY MUST NOT BE COPIED')

    def test_public_store_rejects_private_material_invalid_pem_and_special_files(self):
        for data, error in [(b'-----BEGIN PRIVATE KEY-----\nsecret', ValueError),
                            (b'not a certificate', ValueError)]:
            with self.subTest(data=data):
                self.public.write_bytes(data)
                with self.assertRaises(error): register_public_ca(self.runtime, {}, self.prefix)
        self.public.unlink(); os.mkfifo(self.public)
        with self.assertRaises(ValueError): register_public_ca(self.runtime, {}, self.prefix)
        self.public.unlink(); self.public.symlink_to(self.local_policy)
        with self.assertRaises(OSError): register_public_ca(self.runtime, {}, self.prefix)

    def test_utf8_certificate_descriptions_are_preserved_outside_valid_pem(self):
        data = '# Autoridade pública: Açores, Česká, 日本\n'.encode() + self.public_bytes
        self.public.write_bytes(data)
        register_public_ca(self.runtime, self.maps, self.prefix)
        self.assertEqual(self.public.read_bytes(), data)
        self.assertEqual(self.maps[self.global_ca], self.public)

    def test_every_pem_block_is_required_to_validate(self):
        for malformed in (
            b'-----BEGIN CERTIFICATE-----\n\xc5\x81\n-----END CERTIFICATE-----\n',
            b'-----BEGIN CERTIFICATE-----\nthis is not a certificate\n-----END CERTIFICATE-----\n',
            b'-----BEGIN CERTIFICATE-----\nmissing end marker\n',
        ):
            with self.subTest(block=malformed):
                self.public.write_bytes(self.public_bytes + malformed)
                maps = {}
                with self.assertRaises((ValueError, ssl.SSLError)):
                    register_public_ca(self.runtime, maps, self.prefix)
                self.assertEqual(maps, {})


if __name__ == '__main__':
    unittest.main()
