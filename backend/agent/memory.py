import sqlite3
from pathlib import Path

class Memory:
    def __init__(self, database: Path):
        self.database = database
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS memories (key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    def connect(self): return sqlite3.connect(self.database)
    def save(self, key: str, value: str) -> None:
        with self.connect() as con: con.execute("INSERT OR REPLACE INTO memories(key,value) VALUES (?,?)", (key, value))
    def list(self) -> list[dict[str,str]]:
        with self.connect() as con:
            return [{"key":r[0],"value":r[1],"created_at":r[2]} for r in con.execute("SELECT key,value,created_at FROM memories ORDER BY created_at DESC")]
    def delete(self, key: str) -> bool:
        with self.connect() as con: return con.execute("DELETE FROM memories WHERE key=?", (key,)).rowcount > 0
