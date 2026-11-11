import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from patchcounter.core import db_connect, import_file, get_events, get_groups, add_patch, parse_line

class CoreTests(unittest.TestCase):
    def test_json_line(self):
        self.assertEqual(parse_line('{"level":"ERROR","message":"failed","module":"director"}')['source'], 'director')

    def test_text_line(self):
        self.assertEqual(parse_line('2026-01-01 ERROR failed')['level'], 'ERROR')

    def test_text_timestamp_from_log(self):
        event = parse_line('2026-11-11 06:01:00 ERROR Testfehler Nummer 2')
        self.assertEqual(event['ts'], '2026-11-11T06:01:00')
        self.assertEqual(event['level'], 'ERROR')

    def test_text_timestamp_with_timezone(self):
        event = parse_line('[2026-11-11T06:01:00.123+0100] WARNING message')
        self.assertEqual(event['ts'], '2026-11-11T06:01:00.123+01:00')

    def test_invalid_text_timestamp_falls_back(self):
        event = parse_line('2026-99-99 06:01:00 ERROR bad date')
        self.assertNotIn('2026-99-99', event['ts'])
        self.assertEqual(event['level'], 'ERROR')

    def test_import_deduplicates_source_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.log'
            path.write_text('ERROR failed 1\nERROR failed 2\n', encoding='utf-8')
            with closing(db_connect(Path(folder) / 'db.sqlite')) as db:
                self.assertEqual(import_file(db, path), 2)
                self.assertEqual(import_file(db, path), 0)
                self.assertEqual(len(get_events(db)), 2)
                self.assertEqual(get_groups(db)[0]['occurrences'], 2)

    def test_patch_record(self):
        with tempfile.TemporaryDirectory() as folder:
            with closing(db_connect(Path(folder) / 'db.sqlite')) as db:
                self.assertEqual(add_patch(db, 'abc', 'fixed', '123'), 1)
                self.assertEqual(db.execute('SELECT commit_sha FROM patches').fetchone()[0], '123')

if __name__ == '__main__':
    unittest.main()
