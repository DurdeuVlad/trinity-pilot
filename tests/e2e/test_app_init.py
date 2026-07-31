import ctypes
import sys

if sys.platform == "win32":
    ctypes.windll.ole32.CoInitialize(None)

sys.path.insert(0, str(sys.path[0]))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from trinity_pilot.config import Settings

settings = Settings.from_env()
settings.db_path = ":memory:"

print("a. Initializing TaskStore...")
print("b. Inside TaskStore. Calling open_db...")
import sqlite3

print("c. Opening sqlite3 connection...")
conn = sqlite3.connect(":memory:")
print("d. Executing busy_timeout...")
conn.execute("PRAGMA busy_timeout=10000")
print("e. Executing journal_mode...")
conn.execute("PRAGMA journal_mode=WAL")
print("f. Executing foreign_keys...")
conn.execute("PRAGMA foreign_keys=ON")
print("g. Executing schema...")
from trinity_pilot.memory.db import _SCHEMA

conn.executescript(_SCHEMA)
print("h. Committing...")
conn.commit()
print("i. Completed store setup!")
