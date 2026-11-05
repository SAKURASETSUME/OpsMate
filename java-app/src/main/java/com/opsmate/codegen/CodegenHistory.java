package com.opsmate.codegen;

import com.opsmate.agent.AgentJson;
import com.opsmate.infrastructure.ApiFailure;
import java.sql.Statement;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CodegenHistory {
    private final JdbcTemplate db;
    private final AgentJson json;
    public CodegenHistory(JdbcTemplate db,AgentJson json) {
        this.db=db; this.json=json;
        db.execute("""
            CREATE TABLE IF NOT EXISTS codegen_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,requirement TEXT NOT NULL,params TEXT,
            script TEXT NOT NULL,explanation TEXT,warnings TEXT,usage TEXT,model TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))
            """);
        Set<String> columns=new HashSet<>();
        for (var row:db.queryForList("PRAGMA table_info(codegen_history)")) columns.add(row.get("name").toString());
        for (String column:List.of("steps","scripts"))
            if (!columns.contains(column)) db.execute("ALTER TABLE codegen_history ADD COLUMN "+column+" TEXT");
        boolean hadIndex=db.queryForObject("SELECT count(*) FROM sqlite_master WHERE name='codegen_history_fts'",Integer.class)>0;
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS codegen_history_fts USING fts5(requirement,script,content='codegen_history',content_rowid='id')");
        if (!hadIndex) db.execute("INSERT INTO codegen_history_fts(codegen_history_fts) VALUES ('rebuild')");
    }

    @SuppressWarnings("unchecked")
    @Transactional
    public void save(String requirement,String distro,String notes,Map<String,Object> result,String model) {
        List<Map<String,Object>> scripts=result.get("scripts") instanceof List<?> values ? (List<Map<String,Object>>)values : List.of();
        Map<String,Object> first=scripts.isEmpty() ? result : scripts.getFirst();
        String script=scripts.isEmpty() ? first.get("script").toString()
            : String.join("\n\n",scripts.stream().map(item -> item.get("script").toString()).toList());
        var key=new GeneratedKeyHolder();
        db.update(connection -> {
            var statement=connection.prepareStatement("""
                INSERT INTO codegen_history(requirement,params,script,explanation,warnings,usage,model,steps,scripts)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,Statement.RETURN_GENERATED_KEYS);
            statement.setString(1,requirement);
            statement.setString(2,json.encode(Map.of("distro",distro,"notes",notes)));
            statement.setString(3,script);
            statement.setString(4,json.encode(first.get("explanation")));
            statement.setString(5,json.encode(first.get("warnings")));
            statement.setString(6,first.get("usage").toString());
            statement.setString(7,model);
            statement.setString(8,json.encode(result.getOrDefault("steps",List.of())));
            statement.setString(9,scripts.isEmpty() ? null : json.encode(scripts));
            return statement;
        },key);
        db.update("INSERT INTO codegen_history_fts(rowid,requirement,script) VALUES (?,?,?)",key.getKey().longValue(),requirement,script);
    }

    public List<Map<String,Object>> list(int limit) {
        if (limit<1||limit>2000) throw new ApiFailure(422,"limit 必须在 1–2000 之间");
        return db.queryForList("SELECT id,requirement,created_at,model FROM codegen_history ORDER BY id DESC LIMIT ?",limit);
    }

    public Map<String,Object> detail(long id) {
        var rows=db.queryForList("SELECT * FROM codegen_history WHERE id=?",id);
        if (rows.isEmpty()) throw new ApiFailure(404,"脚本记录不存在");
        var row=rows.getFirst();
        for (String field:List.of("params","explanation","warnings","steps","scripts")) {
            String value=Objects.toString(row.get(field),"");
            // AgentJson parses objects; array columns are wrapped without altering their contents.
            row.put(field,field.equals("params") ? (value.isEmpty() ? Map.of() : json.parse(value))
                : value.isEmpty() ? List.of() : json.parse("{\"items\":"+value+"}").get("items"));
        }
        row.put("need_clarification",false);
        return row;
    }

    public List<Map<String,Object>> search(String query,int limit) {
        if (query.isBlank()) return List.of();
        String expression=String.join(" OR ",Arrays.stream(query.split("\\s+")).limit(8)
            .map(term -> "\""+term.replace("\"","\"\"")+"\"").toList());
        return db.queryForList("""
            SELECT h.id,h.requirement,substr(h.script,1,3000) AS script,h.model
            FROM codegen_history_fts f JOIN codegen_history h ON h.id=f.rowid
            WHERE codegen_history_fts MATCH ? ORDER BY rank LIMIT ?
            """,expression,Math.max(1,Math.min(limit,5)));
    }
}
