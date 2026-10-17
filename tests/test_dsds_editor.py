"""Check the production AWK editor with Google's independent protobuf parser."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.test-deps'))
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

DESCRIPTOR = descriptor_pb2.FileDescriptorProto(name='persistent_properties.proto', syntax='proto2')
PARENT = DESCRIPTOR.message_type.add(name='PersistentProperties')
RECORD = PARENT.nested_type.add(name='PersistentPropertyRecord')
RECORD.field.add(name='name', number=1, type=9, label=1)
RECORD.field.add(name='value', number=2, type=9, label=1)
PARENT.field.add(name='properties', number=1, type=11, label=3,
                 type_name='.PersistentProperties.PersistentPropertyRecord')
POOL = descriptor_pool.DescriptorPool()
POOL.Add(DESCRIPTOR)
PersistentProperties = message_factory.GetMessageClass(POOL.FindMessageTypeByName('PersistentProperties'))
TARGET = 'persist.radio.multisim.config'
BUSYBOX = Path(os.environ.get('EFS_TEST_BUSYBOX') or shutil.which('busybox') or ROOT / '.test-tools/busybox')
if os.environ.get('EFS_REQUIRE_BUSYBOX') == '1' and not BUSYBOX.is_file():
    raise RuntimeError('BusyBox is required by this test run')


def encode_properties(records):
    message = PersistentProperties()
    for name, value in records:
        message.properties.add(name=name, value=value)
    return message.SerializeToString()


def decode_properties(data):
    message = PersistentProperties.FromString(data)
    return [(record.name, record.value) for record in message.properties]


class EditorTests(unittest.TestCase):
    def edit(self, data, mode='set', size=None, use_busybox=True):
        with tempfile.TemporaryDirectory(prefix='dsds-editor-test-') as directory:
            path = Path(directory) / 'properties'
            path.write_bytes(data)
            prefix = [str(BUSYBOX)] if use_busybox and BUSYBOX.exists() else []
            raw = subprocess.run(prefix + ['od', '-An', '-v', '-tu1', str(path)],
                                 capture_output=True, check=True).stdout
            return subprocess.run(prefix + ['awk', '-v', f'expected_size={len(data) if size is None else size}',
                                           '-v', f'mode={mode}', '-f',
                                           str(ROOT / 'recovery/install/persistent-dsds.awk')],
                                  input=raw, capture_output=True, timeout=15,
                                  env={**os.environ, 'LC_ALL': 'C'})

    def assert_enabled(self, original, preserved):
        result = self.edit(original)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = decode_properties(result.stdout)
        self.assertEqual(records, preserved + [(TARGET, 'dsds')])
        self.assertEqual(self.edit(result.stdout, 'check').returncode, 0)
        return result.stdout

    def test_adds_dsds_to_empty_valid_protobuf(self):
        self.assert_enabled(b'', [])

    def test_replaces_single_sim_value(self):
        self.assert_enabled(encode_properties([(TARGET, 'ssss')]), [])

    def test_preserves_unrelated_settings(self):
        records = [('persist.sys.locale', 'en-PK'), ('persist.vendor.demo', 'on')]
        self.assert_enabled(encode_properties(records), records)

    def test_deduplicates_dsds_and_discards_pending_single_sim_override(self):
        preserved = [('persist.keep', 'yes'), ('next_boot.persist.keep', 'later')]
        original = encode_properties([(TARGET, ''), preserved[0], (TARGET, 'ssss'),
                                      ('next_boot.' + TARGET, ''), preserved[1]])
        self.assert_enabled(original, preserved)

    def test_unicode_and_nul_values_are_preserved(self):
        records = [('persist.unicode', 'سلام'), ('persist.nul', 'one\0two')]
        self.assert_enabled(encode_properties(records), records)

    def test_all_binary_bytes_in_unknown_field_are_preserved(self):
        # Top-level field 2, length-delimited, 256 bytes. Tests AWK %c for all
        # byte values including NUL and bytes >= 128, under BusyBox as well.
        unknown = b'\x12\x80\x02' + bytes(range(256))
        original = unknown + encode_properties([('persist.keep', '1')])
        result = self.assert_enabled(original, [('persist.keep', '1')])
        self.assertTrue(result.startswith(unknown))

    def test_unknown_scalar_and_fixed_fields_preserved(self):
        unknown = b'\x10\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01' + b'\x19abcdefgh' + b'\x25ABCD'
        output = self.assert_enabled(unknown, [])
        self.assertTrue(output.startswith(unknown))

    def test_long_values_and_multibyte_lengths(self):
        records = [('persist.long', 'abc' * 1000)]
        self.assert_enabled(encode_properties(records), records)

    def test_noncanonical_unrelated_record_copied_exactly(self):
        # Unrelated property with value before name, and an unknown field.
        payload = b'\x12\x01v\x0a\x0cpersist.keep\x18\x01'
        original = bytes([10, len(payload)]) + payload
        output = self.assert_enabled(original, [('persist.keep', 'v')])
        self.assertTrue(output.startswith(original))

    def test_setting_is_idempotent(self):
        first = self.assert_enabled(encode_properties([(TARGET, ''), ('persist.keep', 'ok')]), [('persist.keep', 'ok')])
        self.assertEqual(self.edit(first).stdout, first)

    def test_check_rejects_missing_duplicate_and_wrong_dsds(self):
        for records in [[], [(TARGET, '')], [(TARGET, 'dsds'), (TARGET, 'dsds')],
                        [(TARGET, 'dsds'), ('next_boot.' + TARGET, '')]]:
            with self.subTest(records=records):
                self.assertNotEqual(self.edit(encode_properties(records), 'check').returncode, 0)

    def test_malformed_data_rejected_without_output(self):
        for data in [b'\x00', b'\x0a\x80', b'\x0a\xff\xff\xff\xff\x10',
                     b'\x0a\x05abc', b'\x0a\x02\x0a\xff', b'\x0b', b'\x19abc',
                     b'\x10' + b'\xff' * 10, b'\x0a\x02\x08\x01']:
            with self.subTest(data=data):
                result = self.edit(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')

    def test_invalid_property_prefix_and_names_rejected(self):
        for name in ['ro.not.persistent', '', 'persist.bad name', 'persist.a\0b', 'persist.' + 'a' * 1025]:
            with self.subTest(name=name[:60]):
                self.assertNotEqual(self.edit(encode_properties([(name, '1')])).returncode, 0)

    def test_incomplete_od_input_rejected(self):
        self.assertNotEqual(self.edit(b'', size=1).returncode, 0)

    def test_oversized_file_rejected(self):
        self.assertNotEqual(self.edit(b'', size=262145).returncode, 0)

    def test_host_and_busybox_editors_agree(self):
        random_source = random.Random(73005)
        for _ in range(30):
            records = [(f'persist.test_{i}', ''.join(chr(random_source.randrange(32, 127)) for _ in range(random_source.randrange(0, 300))))
                       for i in range(random_source.randrange(1, 20))]
            records.insert(random_source.randrange(len(records)), (TARGET, 'ssss'))
            original = encode_properties(records)
            host, busybox = self.edit(original, use_busybox=False), self.edit(original)
            self.assertEqual(host.returncode, 0, host.stderr)
            self.assertEqual(busybox.returncode, 0, busybox.stderr)
            self.assertEqual(host.stdout, busybox.stdout)
            self.assertEqual(decode_properties(host.stdout), [r for r in records if r[0] != TARGET] + [(TARGET, 'dsds')])

    def test_truncated_real_messages_do_not_silently_drop_settings(self):
        original = encode_properties([('persist.one', 'a' * 15), ('persist.two', 'b' * 15)])
        boundary = len(encode_properties([('persist.one', 'a' * 15)]))
        for size in range(1, len(original)):
            if size == boundary:
                continue  # Truncation exactly between complete records is a valid proto.
            result = self.edit(original[:size])
            self.assertNotEqual(result.returncode, 0, f'Accepted invalid truncation at {size}')
            self.assertEqual(result.stdout, b'')


if __name__ == '__main__':
    unittest.main(verbosity=2)
