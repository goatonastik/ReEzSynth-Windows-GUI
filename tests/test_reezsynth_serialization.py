"""Safe JSON/YAML configuration interchange tests; no GUI or renderer."""
import tempfile
import sys
import unittest
from unittest.mock import patch

import yaml
from pathlib import Path

from reezsynth_config import PresetStore, WEIGHTS
from reezsynth_serialization import read_document, write_document


class SerializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reezsynth_yaml_test_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_json_and_yaml_round_trip_without_type_changes(self):
        data = {'format': 'ReEzSynth-Windows-GUI', 'version': 1,
                'guide_weights': {'img_wgt': 6.0}, 'enabled': True, 'empty': None}
        for suffix in ('.json', '.yaml', '.yml'):
            with self.subTest(suffix=suffix):
                path = self.root / ('project' + suffix)
                write_document(path, data)
                self.assertEqual(read_document(path), data)

    def test_yaml_preset_library_uses_same_validation_as_json(self):
        path = self.root / 'presets.yaml'
        store = PresetStore(path)
        store.save('weights', 'Paint', WEIGHTS)
        self.assertEqual(PresetStore(path).groups['weights']['Paint'], WEIGHTS)
        path.write_text('format: ReEzSynth-presets\nversion: 1\ngroups:\n  weights:\n    Bad:\n      unknown: 1\n', encoding='utf-8')
        before = path.read_bytes()
        rejected = PresetStore(path)
        self.assertEqual(rejected.groups['weights'], {})
        self.assertIn('Unknown or invalid', rejected.errors[0])
        self.assertEqual(path.read_bytes(), before)

    def test_yaml_parser_errors_are_bounded_value_errors_with_cause(self):
        for content in ('groups: [\n', 'groups: !unsupported value\n',
                        '? [unhashable, key]\n: value\n'):
            with self.subTest(content=content):
                path = self.root / 'invalid.yaml'
                path.write_text(content, encoding='utf-8')
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, r'Invalid YAML configuration at line \d+, column \d+\.') as caught:
                    read_document(path)
                self.assertIsNotNone(caught.exception.__cause__)
                self.assertIn(caught.exception.__cause__.problem, str(caught.exception))
                self.assertLess(len(str(caught.exception)), 250)
                self.assertEqual(path.read_bytes(), before)

    def test_deep_yaml_parser_recursion_is_a_value_error(self):
        path = self.root / 'deep.yaml'
        depth = sys.getrecursionlimit() * 2
        path.write_text('groups: ' + '[' * depth + '0' + ']' * depth, encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'nesting exceeds the parser limit') as caught:
            read_document(path)
        self.assertIsInstance(caught.exception.__cause__, RecursionError)
        self.assertEqual(path.read_bytes(), before)

    def test_yaml_problem_without_position_is_sanitized_and_truncated(self):
        path = self.root / 'no-position.yaml'
        path.write_text('groups: {}', encoding='utf-8')
        error = yaml.YAMLError('FULL EXCEPTION MUST NOT APPEAR' * 10000)
        error.problem = 'bad\n\t\x00\x1b\u202e token ' + 'x' * 10000
        with patch.object(yaml, 'safe_load', side_effect=error):
            with self.assertRaises(ValueError) as caught:
                read_document(path)
        message = str(caught.exception)
        self.assertTrue(message.startswith('Invalid YAML configuration. bad token '))
        self.assertTrue(message.endswith('...'))
        self.assertTrue(all(c.isprintable() for c in message))
        self.assertNotIn('at line', message)
        self.assertNotIn('FULL EXCEPTION', message)
        self.assertLess(len(message), 200)
        self.assertIs(caught.exception.__cause__, error)

    def test_yaml_reader_error_without_problem_or_position_has_safe_fallback(self):
        path = self.root / 'invalid-character.yaml'
        path.write_text('groups: "\x00"', encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaises(ValueError) as caught:
            read_document(path)
        self.assertEqual(str(caught.exception), 'Invalid YAML configuration.')
        self.assertIsInstance(caught.exception.__cause__, yaml.reader.ReaderError)
        self.assertEqual(path.read_bytes(), before)

    def test_rejects_non_object_yaml_and_json(self):
        for suffix, content in (('.yaml', '- item\n'), ('.json', '[]')):
            path = self.root / ('bad' + suffix)
            path.write_text(content, encoding='utf-8')
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'object'):
                read_document(path)


if __name__ == '__main__':
    unittest.main()
