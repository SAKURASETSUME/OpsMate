package com.opsmate.notes;

import com.opsmate.infrastructure.ApiFailure;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class NotesService {
    private final JdbcTemplate db;
    NotesService(JdbcTemplate db) {
        this.db = db;
        db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))
            """);
    }

    public List<Map<String,Object>> list() {
        return db.queryForList("SELECT id,content,done,created_at FROM notes ORDER BY done ASC,id DESC");
    }

    @Transactional
    public long create(String content) {
        if (content == null || content.strip().isEmpty() || content.length() > 500)
            throw new ApiFailure(422,"待办内容必填且不超过 500 字");
        var key = new GeneratedKeyHolder();
        db.update(connection -> {
            var statement = connection.prepareStatement("INSERT INTO notes(content) VALUES (?)",Statement.RETURN_GENERATED_KEYS);
            statement.setString(1,content.strip());
            return statement;
        },key);
        return key.getKey().longValue();
    }

    @Transactional
    public int done(long id, boolean done) {
        int value = done ? 1 : 0;
        if (db.update("UPDATE notes SET done=? WHERE id=?",value,id) == 0)
            throw new ApiFailure(404,"待办不存在");
        return value;
    }

    @Transactional
    public void delete(long id) {
        if (db.update("DELETE FROM notes WHERE id=?",id) == 0) throw new ApiFailure(404,"待办不存在");
    }
}
