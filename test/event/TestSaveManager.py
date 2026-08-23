import glob
import json
import os
import tempfile
import time
import unittest

from save_manager import SaveManager


class TestSaveManager(unittest.TestCase):

  def _read_all_lines(self, save_dir):
    """Return a list of all parsed JSON objects across all .ndjson files,
    sorted by (mtime, filename) for deterministic reading."""
    files = sorted(
      glob.glob(os.path.join(save_dir, '*.ndjson')),
      key=lambda f: (os.path.getmtime(f), f))
    objects = []
    for f in files:
      with open(f, 'r') as fh:
        for line in fh:
          line = line.strip()
          if line:
            objects.append(json.loads(line))
    return objects

  def test_append_creates_file_and_roundtrips(self):
    with tempfile.TemporaryDirectory() as save_dir:
      manager = SaveManager(save_dir, 0, 0)
      payload = [{"hash": "abc", "points": [[1, 2, 3]]}]
      manager.append(payload)

      files = glob.glob(os.path.join(save_dir, '*.ndjson'))
      self.assertEqual(len(files), 1)
      objects = self._read_all_lines(save_dir)
      self.assertEqual(len(objects), 1)
      self.assertEqual(objects[0], payload)

  def test_size_rotation_no_data_loss(self):
    with tempfile.TemporaryDirectory() as save_dir:
      # Tiny per-file limit forces frequent rotation.
      manager = SaveManager(save_dir, max_file_bytes=10, max_total_bytes=0)

      n = 50
      for i in range(n):
        manager.append({"i": i})

      files = glob.glob(os.path.join(save_dir, '*.ndjson'))
      self.assertGreater(len(files), 1)

      objects = self._read_all_lines(save_dir)
      self.assertEqual(len(objects), n)
      self.assertEqual([o["i"] for o in objects], list(range(n)))

  def test_zero_limits_no_rotation_or_pruning(self):
    with tempfile.TemporaryDirectory() as save_dir:
      manager = SaveManager(save_dir, 0, 0)

      for i in range(20):
        manager.append({"i": i})

      # Single active file, nothing pruned.
      self.assertEqual(len(glob.glob(os.path.join(save_dir, '*.ndjson'))), 1)

  def test_total_cap_prunes_oldest_files(self):
    with tempfile.TemporaryDirectory() as save_dir:
      manager = SaveManager(save_dir, max_file_bytes=0, max_total_bytes=200)

      # Seed two "old" files directly with known sizes and older mtimes.
      old1 = os.path.join(save_dir, '1000000.ndjson')
      old2 = os.path.join(save_dir, '1000001.ndjson')
      with open(old1, 'w') as f:
        f.write('x' * 100)
      with open(old2, 'w') as f:
        f.write('y' * 100)

      old_time = time.time() - 1000
      os.utime(old1, (old_time, old_time))
      os.utime(old2, (old_time, old_time))

      # Append drives total over the cap and should delete oldest files.
      manager.append({"i": 0})

      files = set(os.path.basename(p)
                  for p in glob.glob(os.path.join(save_dir, '*.ndjson')))
      total = sum(
        os.path.getsize(os.path.join(save_dir, f)) for f in files)
      self.assertLessEqual(total, 200)
      # Oldest seeded file was deleted.
      self.assertNotIn('1000000.ndjson', files)

  def test_total_cap_never_deletes_active_file(self):
    with tempfile.TemporaryDirectory() as save_dir:
      manager = SaveManager(save_dir, max_file_bytes=0, max_total_bytes=1)

      # Even with an impossibly small cap, the just-written active file
      # must survive so it remains writable.
      manager.append({"i": 0})

      files = glob.glob(os.path.join(save_dir, '*.ndjson'))
      self.assertEqual(len(files), 1)
      self.assertEqual(self._read_all_lines(save_dir)[0], {"i": 0})

  def test_total_cap_excludes_active_file_by_path(self):
    with tempfile.TemporaryDirectory() as save_dir:
      manager = SaveManager(save_dir, max_file_bytes=0, max_total_bytes=1)

      # First append creates the active file.
      manager.append({"active": True})
      active_file = glob.glob(os.path.join(save_dir, '*.ndjson'))[0]

      # Make a *newer* seed file so the active file is NOT last when
      # sorted by mtime, then force active's mtime into the (old) past.
      seeded = os.path.join(save_dir, '9999999.ndjson')
      with open(seeded, 'w') as f:
        f.write('z' * 100)

      future = time.time() + 1000
      os.utime(seeded, (future, future))
      past = time.time() - 1000
      os.utime(active_file, (past, past))

      # Append drives total over the cap. The active file must survive
      # by path identity even though it is no longer the newest.
      manager.append({"active": True})

      self.assertTrue(os.path.exists(active_file))
      active_basename = os.path.basename(active_file)
      remaining = set(os.path.basename(p)
                      for p in glob.glob(os.path.join(save_dir, '*.ndjson')))
      self.assertIn(active_basename, remaining)

  def test_total_cap_deletes_others_when_active_alone_exceeds_cap(self):
    with tempfile.TemporaryDirectory() as save_dir:
      # Active file will exceed the cap on its own; the pre-seeded old
      # file must still be pruned, with the loop terminating cleanly.
      manager = SaveManager(save_dir, max_file_bytes=0, max_total_bytes=10)

      old = os.path.join(save_dir, '1000000.ndjson')
      with open(old, 'w') as f:
        f.write('x' * 5)
      old_time = time.time() - 1000
      os.utime(old, (old_time, old_time))

      # Append writes a record larger than the cap, making the active
      # file alone exceed max_total_bytes.
      manager.append({"payload": "y" * 100})

      self.assertFalse(os.path.exists(old))

      files = glob.glob(os.path.join(save_dir, '*.ndjson'))
      self.assertEqual(len(files), 1)

  def test_negative_limits_clamped_to_zero(self):
    with tempfile.TemporaryDirectory() as save_dir:
      manager = SaveManager(save_dir, max_file_bytes=-5, max_total_bytes=-5)
      self.assertEqual(manager.max_file_bytes, 0)
      self.assertEqual(manager.max_total_bytes, 0)

      # Negative (clamped to 0) limits behave as unlimited.
      for i in range(20):
        manager.append({"i": i})
      self.assertEqual(len(glob.glob(os.path.join(save_dir, '*.ndjson'))), 1)


if __name__ == '__main__':
  unittest.main()
