package com.opsmate.logs;

import com.opsmate.infrastructure.ApiFailure;
import com.opsmate.infrastructure.RuntimePaths;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.nio.file.*;
import java.sql.Statement;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Consumer;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.*;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.*;

@Service
public class LogService {
    public static final int MAX_BYTES = 50*1024*1024;
    private static final List<String> LEVELS = List.of("ERROR","WARN","INFO","DEBUG","");
    private final JdbcTemplate db;
    private final Path rawDirectory;

    LogService(JdbcTemplate db,RuntimePaths paths) throws java.io.IOException {
        this.db = db;
        rawDirectory = paths.data().resolve("logs");
        Files.createDirectories(rawDirectory);
        db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,filename TEXT,
            size_bytes INTEGER NOT NULL,line_count INTEGER NOT NULL,format_guess TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))
            """);
        db.execute("""
            CREATE TABLE IF NOT EXISTS log_lines (
            log_id INTEGER NOT NULL,line_no INTEGER NOT NULL,level TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,PRIMARY KEY(log_id,line_no))
            """);
        db.execute("CREATE INDEX IF NOT EXISTS idx_lines_level ON log_lines(log_id,level)");
        db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,log_id INTEGER NOT NULL,kind TEXT NOT NULL DEFAULT 'llm',
            model TEXT,content TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))
            """);
    }

    public Map<String,Object> get(long id) {
        var rows = db.queryForList("SELECT * FROM logs WHERE id=?",id);
        if (rows.isEmpty()) throw new ApiFailure(404,"日志不存在");
        var result = rows.getFirst();
        Map<String,Object> counts = new LinkedHashMap<>();
        for (String level : LEVELS) counts.put(level,0);
        for (var count : db.queryForList("SELECT level,count(*) n FROM log_lines WHERE log_id=? GROUP BY level",id))
            counts.put(count.get("level").toString(),count.get("n"));
        result.put("level_stats",counts);
        return result;
    }

    public List<Map<String,Object>> list() {
        return db.queryForList("SELECT id FROM logs ORDER BY id DESC").stream()
            .map(row -> get(((Number)row.get("id")).longValue())).toList();
    }

    @Transactional(rollbackFor=Exception.class)
    public Map<String,Object> importLog(String title,byte[] raw,String filename) {
        if (title==null || title.strip().isEmpty() || title.length()>200)
            throw new ApiFailure(400,"日志标题必填且不能超过 200 字");
        if (raw.length>MAX_BYTES) throw new ApiFailure(413,"单份日志不能超过 50MB，请先 split/grep 裁剪");
        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(raw)).toString();
        } catch (CharacterCodingException error) {
            throw new ApiFailure(400,"日志必须是 UTF-8 文本，请转换编码后上传");
        }
        if (text.startsWith("\uFEFF")) text=text.substring(1);
        if (text.indexOf('\0')>=0) throw new ApiFailure(400,"不支持二进制日志，请上传 UTF-8 文本");
        if (text.isEmpty()) throw new ApiFailure(400,"日志内容不能为空");
        List<String> lines = new ArrayList<>(Arrays.asList(text.split("\r\n|[\n\r\u000B\f\u001C-\u001E\u0085\u2028\u2029]",-1)));
        if (lines.getLast().isEmpty()) lines.removeLast();
        var key = new GeneratedKeyHolder();
        db.update(connection -> {
            var statement = connection.prepareStatement(
                "INSERT INTO logs(title,filename,size_bytes,line_count,format_guess) VALUES (?,?,?,?,?)",Statement.RETURN_GENERATED_KEYS);
            statement.setString(1,title.strip());
            statement.setString(2,filename);
            statement.setInt(3,raw.length);
            statement.setInt(4,lines.size());
            statement.setString(5,LogRules.format(lines));
            return statement;
        },key);
        long id = key.getKey().longValue();
        for (int start=0; start<lines.size(); start+=5000) {
            int base = start;
            int batch = Math.min(5000,lines.size()-base);
            db.batchUpdate("INSERT INTO log_lines(log_id,line_no,level,text) VALUES (?,?,?,?)",new BatchPreparedStatementSetter() {
                public int getBatchSize() { return batch; }
                public void setValues(java.sql.PreparedStatement ps,int i) throws java.sql.SQLException {
                    String line = lines.get(base+i);
                    ps.setLong(1,id); ps.setInt(2,base+i+1); ps.setString(3,LogRules.level(line)); ps.setString(4,line);
                }
            });
        }
        if (filename!=null) {
            Path target = rawDirectory.resolve(id+".txt");
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCompletion(int status) {
                    if (status!=STATUS_COMMITTED) {
                        try { if (Files.isRegularFile(target)) Files.deleteIfExists(target); }
                        catch (java.io.IOException ignored) { /* Non-sensitive orphan remains for repair. */ }
                    }
                }
            });
            try { Files.write(target,raw); }
            catch (java.io.IOException failure) { throw new ApiFailure(500,"原始日志副本保存失败"); }
        }
        return get(id);
    }

    public record Filter(String sql,List<Object> parameters,String keyword,Pattern regex) {}

    public Filter filters(long id,String levels,String keyword,String regex) {
        List<Object> parameters = new ArrayList<>();
        parameters.add(id);
        String sql = "log_id=?";
        if (!levels.isEmpty()) {
            var values = Arrays.stream(levels.split(",",-1)).map(String::strip)
                .map(value -> value.toUpperCase(Locale.ROOT)).map(value -> value.equals("UNKNOWN") ? "" : value).toList();
            if (!LEVELS.containsAll(values)) throw new ApiFailure(400,"日志级别无效");
            sql += " AND level IN ("+String.join(",",Collections.nCopies(values.size(),"?"))+")";
            parameters.addAll(values);
        }
        Pattern compiled = null;
        if (!regex.isEmpty()) {
            try { compiled = Pattern.compile(regex.replace("(?P<","(?<"),Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE|Pattern.UNICODE_CHARACTER_CLASS); }
            catch (java.util.regex.PatternSyntaxException failure) { throw new ApiFailure(400,"正则表达式无效"); }
        }
        return new Filter(sql,parameters,keyword.toLowerCase(Locale.ROOT),compiled);
    }

    private void scan(Filter filter,String order,Consumer<Map<String,Object>> consumer) {
        String direction = order.equals("desc") ? "DESC" : "ASC";
        db.query("SELECT line_no,level,text FROM log_lines WHERE "+filter.sql()+" ORDER BY line_no "+direction,
            (RowCallbackHandler) row -> {
                String text = row.getString("text");
                if (!text.toLowerCase(Locale.ROOT).contains(filter.keyword())) return;
                if (filter.regex()!=null && !filter.regex().matcher(text).find()) return;
                consumer.accept(Map.of("line_no",row.getInt("line_no"),"level",row.getString("level"),"text",text));
            },filter.parameters().toArray());
    }

    public Map<String,Object> query(long id,String level,String q,String regex,int offset,int limit,String order) {
        get(id);
        if (offset<0 || limit<1 || limit>2000 || !Set.of("asc","desc").contains(order))
            throw new ApiFailure(422,"分页或排序参数无效");
        Filter filter = filters(id,level,q,regex);
        AtomicInteger total = new AtomicInteger();
        List<Map<String,Object>> result = new ArrayList<>();
        scan(filter,order,row -> {
            int index = total.getAndIncrement();
            if (index>=offset && index<(long)offset+limit) result.add(row);
        });
        return Map.of("total",total.get(),"lines",result);
    }

    public void export(Filter filter,Consumer<String> output) {
        scan(filter,"asc",row -> output.accept(row.get("line_no")+"\t"+row.get("text")+"\n"));
    }

    public Map<String,Object> stats(long id) {
        var metadata = get(id);
        LogRules.Clusters clusters = new LogRules.Clusters();
        scan(filters(id,"","",""),"asc",row -> clusters.accept((int)row.get("line_no"),row.get("level").toString(),row.get("text").toString()));
        var result = clusters.finish();
        result.put("level_counts",metadata.get("level_stats"));
        result.put("format_guess",metadata.get("format_guess"));
        return result;
    }

    @Transactional(rollbackFor=Exception.class)
    public void delete(long id) {
        get(id);
        db.update("DELETE FROM log_lines WHERE log_id=?",id);
        db.update("DELETE FROM reports WHERE log_id=?",id);
        db.update("DELETE FROM logs WHERE id=?",id);
        try { Files.deleteIfExists(rawDirectory.resolve(id+".txt")); }
        catch (java.io.IOException failure) { throw new ApiFailure(500,"无法删除原始副本"); }
    }
}
