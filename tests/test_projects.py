import tempfile
import unittest
from pathlib import Path
from patchcounter.core import (
    db_connect, create_project, update_project, delete_project, list_projects,
    add_source, update_source, delete_source, scan_sources, get_events,
)

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = db_connect(self.root / 'patchcounter.db')

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_project_crud(self):
        project_id = create_project(self.db, 'App A', str(self.root))
        self.assertEqual(list_projects(self.db)[0]['name'], 'App A')
        self.assertTrue(update_project(self.db, project_id, 'App B', str(self.root), True))
        self.assertTrue(list_projects(self.db)[0]['enabled'])
        self.assertTrue(delete_project(self.db, project_id))
        self.assertEqual(list_projects(self.db), [])

    def test_sources_and_scan(self):
        project_id = create_project(self.db, 'App', str(self.root))
        source_id = add_source(self.db, project_id, str(self.root), '*.log', False)
        self.assertTrue(update_project(self.db, project_id, 'App', str(self.root), True))
        log = self.root / 'app.log'
        log.write_text('ERROR first\n', encoding='utf-8')
        self.assertEqual(scan_sources(self.db)['imported'], 1)
        self.assertEqual(scan_sources(self.db)['imported'], 0)
        log.write_text('ERROR first\nERROR second\n', encoding='utf-8')
        self.assertEqual(scan_sources(self.db)['imported'], 1)
        self.assertEqual(len(get_events(self.db, project_id=project_id)), 2)
        self.assertTrue(update_source(self.db, source_id, str(self.root), '*.log', False, False))
        log.write_text('ERROR first\nERROR second\nERROR third\n', encoding='utf-8')
        self.assertEqual(scan_sources(self.db)['imported'], 0)
        self.assertTrue(delete_source(self.db, source_id))

    def test_pause_project(self):
        project_id = create_project(self.db, 'Paused', str(self.root))
        add_source(self.db, project_id, str(self.root), '*.log')
        (self.root / 'paused.log').write_text('ERROR ignored\n', encoding='utf-8')
        self.assertEqual(scan_sources(self.db)['imported'], 0)

    def test_database_migration_keeps_old_events(self):
        with self.db:
            self.db.execute("""INSERT INTO events(ts,level,source,message,fingerprint,source_file,source_line)
                VALUES ('now','ERROR','legacy','old','123','old.log',1)""")
        self.db.close()
        self.db = db_connect(self.root / 'patchcounter.db')
        self.assertEqual(get_events(self.db)[0]['message'], 'old')
        self.assertIsNone(get_events(self.db)[0]['project_id'])

if __name__ == '__main__':
    unittest.main()
