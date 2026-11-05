package com.opsmate.kb;

import com.opsmate.infrastructure.ApiFailure;
import java.nio.charset.StandardCharsets;
import java.sql.Statement;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class WorkbenchService {
    public static final Set<String> FORMATS = Set.of("yaml","nginx","keepalived","properties","json","text");
    private final JdbcTemplate db;

    WorkbenchService(JdbcTemplate db) {
        this.db = db;
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, format TEXT NOT NULL,
            content TEXT NOT NULL, shared INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))
            """);
    }

    public List<Map<String,Object>> list() {
        return db.queryForList("""
            SELECT id,name,format,shared,LENGTH(CAST(content AS BLOB)) AS size_bytes,updated_at
            FROM user_configs ORDER BY updated_at DESC,id DESC
            """);
    }

    public Map<String,Object> get(long id) {
        var rows = db.queryForList("""
            SELECT id,name,format,content,shared,LENGTH(CAST(content AS BLOB)) AS size_bytes,created_at,updated_at
            FROM user_configs WHERE id=?
            """,id);
        if (rows.isEmpty()) throw new ApiFailure(404,"配置不存在");
        return rows.getFirst();
    }

    private void validate(String name,String format,String content) {
        if (name == null || name.strip().isEmpty() || name.length()>80)
            throw new ApiFailure(422,"配置名称必填且不超过 80 字");
        if (!FORMATS.contains(format)) throw new ApiFailure(422,"配置格式无效");
        if (content.getBytes(StandardCharsets.UTF_8).length>2*1024*1024)
            throw new ApiFailure(413,"配置内容超过 2MB 上限，请先拆分");
    }

    @Transactional
    public Map<String,Object> create(String name,String format,String content) {
        validate(name,format,content);
        var key = new GeneratedKeyHolder();
        db.update(connection -> {
            var statement = connection.prepareStatement(
                "INSERT INTO user_configs(name,format,content,shared) VALUES (?,?,?,0)",Statement.RETURN_GENERATED_KEYS);
            statement.setString(1,name.strip());
            statement.setString(2,format);
            statement.setString(3,content);
            return statement;
        },key);
        return Map.of("id",key.getKey().longValue(),"name",name.strip(),"format",format);
    }

    @Transactional
    public void update(long id,String name,String format,String content) {
        validate(name,format,content);
        if (db.update("""
            UPDATE user_configs SET name=?,format=?,content=?,updated_at=datetime('now','localtime') WHERE id=?
            """,name.strip(),format,content,id)==0) throw new ApiFailure(404,"配置不存在");
    }

    @Transactional
    public void delete(long id) {
        if (db.update("DELETE FROM user_configs WHERE id=?",id)==0) throw new ApiFailure(404,"配置不存在");
    }

    @Transactional
    public int share(long id,boolean shared) {
        int value = shared ? 1 : 0;
        if (db.update("UPDATE user_configs SET shared=? WHERE id=?",value,id)==0)
            throw new ApiFailure(404,"配置不存在");
        return value;
    }

    public Map<String,Object> readShared(String name) {
        var rows = db.queryForList("SELECT id,name,format,content FROM user_configs WHERE name=? AND shared=1 ORDER BY id DESC LIMIT 1",name);
        if (rows.isEmpty()) return Map.of("ok",false,"error","配置不存在或未共享");
        var item = rows.getFirst();
        String content = item.get("content").toString();
        item.put("content",content.substring(0,Math.min(content.length(),4000)));
        item.put("truncated",content.length()>4000);
        return Map.of("ok",true,"result",item);
    }
}
