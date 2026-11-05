CREATE INDEX idx_asst_msg_session ON assistant_messages(session_id, id);

CREATE INDEX idx_lines_level ON log_lines(log_id,level);

CREATE TABLE assistant_attachments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER,
          message_id INTEGER,
          name TEXT NOT NULL,
          mime TEXT NOT NULL,
          kind TEXT NOT NULL,
          size_bytes INTEGER NOT NULL,
          path TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE assistant_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          summary TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE assistant_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          workspace TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE assistant_summaries (
          session_id INTEGER PRIMARY KEY,
          compressed_until INTEGER NOT NULL,
          summary TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE codegen_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, requirement TEXT NOT NULL,
            params TEXT, script TEXT NOT NULL, explanation TEXT, warnings TEXT, usage TEXT,
            model TEXT, steps TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')), scripts TEXT);

CREATE VIRTUAL TABLE codegen_history_fts USING fts5(
            requirement, script, content='codegen_history', content_rowid='id', tokenize='unicode61');

CREATE TABLE 'codegen_history_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;

CREATE TABLE 'codegen_history_fts_data'(id INTEGER PRIMARY KEY, block BLOB);

CREATE TABLE 'codegen_history_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);

CREATE TABLE 'codegen_history_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;

CREATE TABLE log_lines (
          log_id INTEGER NOT NULL, line_no INTEGER NOT NULL, level TEXT NOT NULL DEFAULT '',
          text TEXT NOT NULL, PRIMARY KEY(log_id,line_no));

CREATE TABLE logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, filename TEXT,
          size_bytes INTEGER NOT NULL, line_count INTEGER NOT NULL, format_guess TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          content TEXT NOT NULL,
          done INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT, log_id INTEGER NOT NULL,
          kind TEXT NOT NULL DEFAULT 'llm', model TEXT, content TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE user_configs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          format TEXT NOT NULL,
          content TEXT NOT NULL,
          shared INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));

CREATE TABLE version_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          package TEXT NOT NULL,
          version TEXT NOT NULL,
          description TEXT,
          release_date TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
