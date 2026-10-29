import pathlib,unittest
class LibraryRemovalTest(unittest.TestCase):
 def test_removal_keeps_original_identity_immutable_and_filters_new_choices(self):
  root=pathlib.Path(__file__).resolve().parents[2]
  migration=root/'packages/shared/video_service/postgres/migrations/032_library_removal.sql'
  self.assertTrue(migration.exists(),'history-preserving library removal is missing')
  sql=migration.read_text()
  self.assertIn('library_removed_at',sql)
  self.assertIn("TG_OP = 'DELETE'",sql)
  self.assertIn('to_jsonb(NEW)',sql)
  self.assertIn('to_jsonb(OLD)',sql)
  self.assertNotIn('DISABLE TRIGGER',sql)
  self.assertNotIn('GRANT ',sql)
  intake=(root/'packages/shared/video_service/postgres/intake.py').read_text()
  self.assertIn('library_removed_at IS NULL',intake)
if __name__=='__main__':unittest.main()
