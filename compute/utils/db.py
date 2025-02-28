import os
import sqlite3

import bittensor as bt
from dotenv import load_dotenv

load_dotenv()

class ComputeDb:
    def __init__(self):
        # Connect to the database (or create it if it doesn't exist)
        try:
            self.conn = sqlite3.connect(os.getenv("SQLITE_DB_PATH", "database.db"), check_same_thread=False)
            self.init()
        except (sqlite3.Error, Exception) as e:
            bt.logging.error(f"ComputeDb: Failed to connect to and initialize the SQLite database: {e}")
            self.conn = None

    def close(self):
        self.conn.close()

    def get_cursor(self):
        return self.conn.cursor()

    def init(self):
        cursor = self.get_cursor()

        try:
            cursor.execute("CREATE TABLE IF NOT EXISTS miner (uid INTEGER PRIMARY KEY, ss58_address TEXT UNIQUE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS miner_details (id INTEGER PRIMARY KEY, hotkey TEXT UNIQUE, details TEXT, no_specs_count INTEGER DEFAULT 0)")
            cursor.execute("CREATE TABLE IF NOT EXISTS tb (id INTEGER PRIMARY KEY, hotkey TEXT, details TEXT)")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS challenge_details (
                    uid INTEGER,
                    ss58_address TEXT,
                    success BOOLEAN,
                    elapsed_time REAL,
                    difficulty INTEGER,
                    created_at TIMESTAMP,
                    FOREIGN KEY (uid) REFERENCES miner(uid) ON DELETE CASCADE,
                    FOREIGN KEY (ss58_address) REFERENCES miner(ss58_address) ON DELETE CASCADE
                )
            """
            )
            cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (id INTEGER PRIMARY KEY, hotkey TEXT UNIQUE, details TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS allocation (id INTEGER PRIMARY KEY, hotkey TEXT UNIQUE, details TEXT)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_uid ON challenge_details (uid)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ss58_address ON challenge_details (ss58_address)")
            cursor.execute("CREATE TABLE IF NOT EXISTS wandb_runs (hotkey TEXT PRIMARY KEY, run_id TEXT NOT NULL)")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pog_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hotkey TEXT,
                    gpu_name TEXT,
                    num_gpus INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (hotkey) REFERENCES miner_details (hotkey) ON DELETE CASCADE
                )
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stats (
                    uid INTEGER PRIMARY KEY,
                    hotkey TEXT NOT NULL,
                    gpu_specs TEXT,
                    score REAL,
                    allocated BOOLEAN,
                    own_score BOOLEAN,
                    reliability_score REAL,  -- Optional reliability score
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (hotkey) REFERENCES miner_details (hotkey) ON DELETE CASCADE
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hotkey_reliability_report (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP,
                    hotkey TEXT,
                    rentals INTEGER,
                    failed INTEGER,
                    rentals_14d INTEGER,
                    failed_14d INTEGER,
                    aborted INTEGER,
                    rental_best INTEGER,
                    blacklisted BOOLEAN
                )
            """
            )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            bt.logging.error(f"ComputeDb error: {e}")
        finally:
            cursor.close()
