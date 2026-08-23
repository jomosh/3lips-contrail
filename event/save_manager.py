"""
@file save_manager.py
@brief Size-limited NDJSON save file management for 3lips.
@author jomosh

Rotates the active .ndjson save file by size and enforces a total
directory size cap by deleting the oldest files.  This replaces the
previous age (retention-hours) based cleanup, which could not bound the
size of the active file and therefore allowed the save directory to grow
until it filled the disk.

Rotation and pruning are both driven purely by byte sizes:

  * max_file_bytes  — when the active file reaches this size, the next
                      append starts a fresh timestamped file.
  * max_total_bytes — after appending, the oldest .ndjson files are
                      deleted until the directory total no longer exceeds
                      this size.

Either limit may be set to 0 to disable that particular check.
"""

import glob
import json
import os
import time


class SaveManager:

  """
  @class SaveManager
  @brief Append JSON snapshots to size-rotated .ndjson files under a
         directory, capping total on-disk usage.
  """

  def __init__(self, save_dir, max_file_bytes=0, max_total_bytes=0):

    """
    @brief Constructor for SaveManager.
    @param save_dir (str): Directory where .ndjson files are stored.
    @param max_file_bytes (int): Per-file rotation threshold in bytes.
           The current file is retired once it reaches this size.
           0 disables per-file rotation.
    @param max_total_bytes (int): Total directory cap in bytes.  The
           oldest .ndjson files are deleted until the directory total
           is at or below this size.  0 disables the total cap.
    """

    self.save_dir = save_dir
    self.max_file_bytes = max_file_bytes
    self.max_total_bytes = max_total_bytes
    self._active_file = None
    self._counter = 0

  def _make_active_file(self):

    """Open a fresh timestamped .ndjson file for appending.

    A monotonically increasing counter is appended to the timestamp so
    that multiple rotations within the same second still produce unique
    file names."""

    os.makedirs(self.save_dir, exist_ok=True)
    self._counter += 1
    self._active_file = os.path.join(
      self.save_dir, f"{int(time.time())}-{self._counter}.ndjson")

  def append(self, api_object):

    """
    @brief Append one JSON line representing api_object to the active
           save file, rotating by size and pruning oldest files to
           honour the total-size cap.
    @param api_object (list|dict): The API state to serialise.
    @return None.
    """

    os.makedirs(self.save_dir, exist_ok=True)

    if self._active_file is None:
      self._make_active_file()

    size = 0
    if os.path.exists(self._active_file):
      size = os.path.getsize(self._active_file)

    # Size-only rotation: start a new file if the current one has
    # reached (or exceeded) the per-file limit.
    if self.max_file_bytes > 0 and size >= self.max_file_bytes:
      self._make_active_file()

    with open(self._active_file, 'a') as json_file:
      json.dump(api_object, json_file)
      json_file.write('\n')

    if self.max_total_bytes > 0:
      self._enforce_total_cap()

  def _list_files(self):

    """Return all .ndjson files under save_dir sorted oldest-first
       (by modification time, then name for determinism)."""

    files = glob.glob(os.path.join(self.save_dir, '*.ndjson'))
    files = [f for f in files if os.path.isfile(f)]
    files.sort(key=lambda f: (os.path.getmtime(f), f))
    return files

  def _enforce_total_cap(self):

    """
    @brief Delete the oldest .ndjson files until the directory total is
           at or below max_total_bytes.  The active file (most recently
           written) is never deleted.
    @return None.
    """

    files = self._list_files()
    if not files:
      return

    total = sum(os.path.getsize(f) for f in files)
    if total <= self.max_total_bytes:
      return

    # Never delete the most-recently-written file, even if it alone is
    # larger than the cap — it must stay writable for this epoch.
    files_deletable = files[:-1]

    for f in files_deletable:
      if total <= self.max_total_bytes:
        break
      try:
        size = os.path.getsize(f)
        os.remove(f)
        total -= size
      except OSError:
        pass