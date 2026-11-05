package com.opsmate.versions;

import com.opsmate.infrastructure.ApiFailure;
import java.sql.Statement;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class VersionsService {
    private final JdbcTemplate db;
    VersionsService(JdbcTemplate db) {
        this.db = db;
        db.execute("""
            CREATE TABLE IF NOT EXISTS version_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, package TEXT NOT NULL, version TEXT NOT NULL,
            description TEXT, release_date TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))
            """);
    }

    private boolean hit(Map<String,Object> row, String term, String... fields) {
        String text = Arrays.stream(fields).map(field -> Objects.toString(row.get(field),""))
            .reduce("",(a,b) -> a + " " + b).toLowerCase(Locale.ROOT);
        return text.contains(term.strip().toLowerCase(Locale.ROOT));
    }

    public List<Map<String,Object>> list(String q,String pkg,String version,String description) {
        return db.queryForList("SELECT * FROM version_records ORDER BY id DESC").stream()
            .filter(row -> hit(row,q,"package","version","description"))
            .filter(row -> hit(row,pkg,"package"))
            .filter(row -> hit(row,version,"version"))
            .filter(row -> hit(row,description,"description")).toList();
    }

    @Transactional
    public Map<String,Object> create(String pkg,String version,String description,String date) {
        var key = new GeneratedKeyHolder();
        db.update(connection -> {
            var statement = connection.prepareStatement(
                "INSERT INTO version_records(package,version,description,release_date) VALUES (?,?,?,?)",
                Statement.RETURN_GENERATED_KEYS);
            statement.setString(1,pkg.strip());
            statement.setString(2,version.strip());
            statement.setString(3,description.strip());
            statement.setString(4,date.strip());
            return statement;
        },key);
        return Map.of("id",key.getKey().longValue(),"package",pkg.strip(),"version",version.strip());
    }

    @Transactional
    public void update(long id,String pkg,String version,String description,String date) {
        if (db.update("UPDATE version_records SET package=?,version=?,description=?,release_date=? WHERE id=?",
                pkg.strip(),version.strip(),description.strip(),date.strip(),id) == 0)
            throw new ApiFailure(404,"版本记录不存在");
    }

    @Transactional
    public void delete(long id) {
        if (db.update("DELETE FROM version_records WHERE id=?",id) == 0)
            throw new ApiFailure(404,"版本记录不存在");
    }
}
