import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from patchcounter.core import db_connect, import_file, read_raw_lines, verified_log_path

class RawLogTests(unittest.TestCase):
    def test_raw_pagination_and_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            logfile = root / 'sample.log'
            content = 'INFO one\nERROR two\nDEBUG three\n'
            logfile.write_text(content, encoding='utf-8')
            with closing(db_connect(root / 'test.db')) as db:
                import_file(db, logfile)
                first = read_raw_lines(db, str(logfile), 1, 2)
                self.assertEqual([x['number'] for x in first['lines']], [1, 2])
                self.assertEqual(first['lines'][1]['text'], 'ERROR two')
                self.assertTrue(first['has_more'])
                self.assertEqual(read_raw_lines(db, str(logfile), 3, 2)['lines'][0]['text'], 'DEBUG three')
            self.assertEqual(logfile.read_text(encoding='utf-8'), content)

    def test_unindexed_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            other = root / 'private.txt'
            other.write_text('private', encoding='utf-8')
            with closing(db_connect(root / 'test.db')) as db:
                with self.assertRaises(ValueError):
                    verified_log_path(db, str(other))
                with self.assertRaises(ValueError):
                    read_raw_lines(db, str(other))
                with self.assertRaises(ValueError):
                    read_raw_lines(db, str(other), 0, 200)

if __name__ == '__main__':
    unittest.main()
