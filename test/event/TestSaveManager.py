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


if __name__ == '__main__':
  unittest.main()