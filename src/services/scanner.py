import os
import sqlite3
from pathlib import Path


class Scanner:
    def __init__(self, scan_dir, db_path):
        self.scan_dir = Path(scan_dir)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('''
                         CREATE TABLE IF NOT EXISTS scanned_files
                         (
                             path
                             TEXT
                             PRIMARY
                             KEY,
                             mtime
                             REAL,
                             size
                             INTEGER
                         )
                         ''')
            conn.commit()
        finally:
            conn.close()

    def is_new_or_modified(self, file_path):
        try:
            stats = os.stat(file_path)
        except (FileNotFoundError, OSError):
            # File doesn't exist or can't be accessed
            raise FileNotFoundError(f"Cannot access file: {file_path}")

        mtime = stats.st_mtime
        size = stats.st_size

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute('SELECT mtime, size FROM scanned_files WHERE path = ?', (str(file_path),))
            row = cursor.fetchone()
            if row is None:
                return True
            saved_mtime, saved_size = row
            return mtime > saved_mtime or size != saved_size
        finally:
            conn.close()

    def mark_as_scanned(self, file_path):
        stats = os.stat(file_path)
        mtime = stats.st_mtime
        size = stats.st_size

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('''
                INSERT OR REPLACE INTO scanned_files (path, mtime, size)
                VALUES (?, ?, ?)
            ''', (str(file_path), mtime, size))
            conn.commit()
        finally:
            conn.close()

    def get_new_files(self):
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.mp4', '.avi', '.mov', '.mkv'}
        for root, _, files in os.walk(self.scan_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in extensions:
                    try:
                        if self.is_new_or_modified(file_path):
                            yield file_path
                    except FileNotFoundError:
                        # File was deleted/moved during scan
                        continue
