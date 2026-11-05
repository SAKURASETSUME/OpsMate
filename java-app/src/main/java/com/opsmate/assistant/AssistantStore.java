package com.opsmate.assistant;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsmate.infrastructure.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.sql.Statement;
import java.util.*;
import java.util.regex.Pattern;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Original assistant schema; a completed turn and attachment ownership commit together. */
@Service
public class AssistantStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final Path files,proposals;
    private static final Pattern SECRET=Pattern.compile("\\b(?:sk-[A-Za-z0-9]{16,}|[A-Za-z0-9_\\-]{40,}|[A-Za-z0-9+\\-/]{40,}={0,2})\\b");
    private static final Set<String> TEXT=Set.of("txt","md","log","conf","cfg","ini","yaml","yml","json","properties","toml","csv","sh","bash","py","pl","rb","go","js","ts","java","sql","xml","html","css","env","service");
    private static final Set<String> IMAGES=Set.of("png","jpg","jpeg","gif","webp","bmp");

    public AssistantStore(JdbcTemplate db,ObjectMapper json,RuntimePaths paths) throws java.io.IOException {
        this.db=db; this.json=json;
        files=paths.data().resolve("assistant_files"); proposals=paths.data().resolve("agent_files");
        Files.createDirectories(files); Files.createDirectories(proposals);
        db.execute("CREATE TABLE IF NOT EXISTS assistant_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,workspace TEXT,created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))");
        db.execute("CREATE TABLE IF NOT EXISTS assistant_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,summary TEXT,created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))");
        db.execute("CREATE INDEX IF NOT EXISTS idx_asst_msg_session ON assistant_messages(session_id,id)");
        db.execute("CREATE TABLE IF NOT EXISTS assistant_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER,message_id INTEGER,name TEXT NOT NULL,mime TEXT NOT NULL,kind TEXT NOT NULL,size_bytes INTEGER NOT NULL,path TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))");
        db.execute("CREATE TABLE IF NOT EXISTS assistant_summaries (session_id INTEGER PRIMARY KEY,compressed_until INTEGER NOT NULL,summary TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))");
        for (String table:List.of("assistant_sessions","assistant_messages")) {
            String column=table.endsWith("sessions")?"workspace":"summary";
            if (db.queryForList("PRAGMA table_info("+table+")").stream().noneMatch(row -> column.equals(row.get("name"))))
                db.execute("ALTER TABLE "+table+" ADD COLUMN "+column+" TEXT");
        }
    }
    public static String clip(String text,int limit) {
        return text.codePointCount(0,text.length())<=limit?text:text.substring(0,text.offsetByCodePoints(0,limit));
    }
    public static String mask(String text) {
        return SECRET.matcher(text).replaceAll(match -> match.group().substring(0,4)+"***"+match.group().substring(match.group().length()-4));
    }
    private long insert(String sql,Object... values) {
        var key=new GeneratedKeyHolder();
        db.update(connection -> {
            var statement=connection.prepareStatement(sql,Statement.RETURN_GENERATED_KEYS);
            for (int i=0;i<values.length;i++) statement.setObject(i+1,values[i]);
            return statement;
        },key);
        return Objects.requireNonNull(key.getKey()).longValue();
    }
    private String encode(Object value) {
        try { return json.writeValueAsString(value); }
        catch (Exception failure) { throw new IllegalStateException("会话内容无法保存"); }
    }
    public Map<String,Object> decode(String text) {
        try { return json.readValue(text,new TypeReference<LinkedHashMap<String,Object>>(){}); }
        catch (Exception failure) { return new LinkedHashMap<>(); }
    }
    public List<Map<String,Object>> sessions(String workspace) {
        String sql="SELECT id,title,workspace,updated_at FROM assistant_sessions";
        if (workspace==null) return db.queryForList(sql+" ORDER BY updated_at DESC,id DESC");
        if (workspace.equals("__none__")) return db.queryForList(sql+" WHERE workspace IS NULL OR workspace='' ORDER BY updated_at DESC,id DESC");
        return db.queryForList(sql+" WHERE workspace=? ORDER BY updated_at DESC,id DESC",workspace);
    }
    private void requireSession(long id) {
        if (db.queryForObject("SELECT count(*) FROM assistant_sessions WHERE id=?",Integer.class,id)==0)
            throw new ApiFailure(404,"会话不存在");
    }
    public List<Map<String,Object>> messages(long id) {
        requireSession(id);
        var rows=db.queryForList("SELECT id,role,content,summary FROM assistant_messages WHERE session_id=? ORDER BY id",id);
        var attachments=db.queryForList("SELECT id,message_id,name,mime,kind,size_bytes FROM assistant_attachments WHERE session_id=? AND message_id IS NOT NULL ORDER BY id",id);
        for (var row:rows) row.put("attachments",attachments.stream().filter(a -> Objects.equals(a.get("message_id"),row.get("id"))).toList());
        return rows;
    }
    public Map<String,Object> attachment(long id) {
        var rows=db.queryForList("SELECT id,name,mime,kind,size_bytes,path,session_id,message_id FROM assistant_attachments WHERE id=?",id);
        if (rows.isEmpty()) throw new ApiFailure(404,"附件不存在");
        return rows.getFirst();
    }
    public Path attachmentPath(Map<String,Object> item) {
        try {
            Path path=Path.of(item.get("path").toString()).toRealPath();
            if (!path.startsWith(files.toRealPath())||!Files.isRegularFile(path)) throw new java.io.IOException();
            return path;
        } catch (Exception failure) { throw new ApiFailure(404,"附件不存在"); }
    }
    @Transactional
    public Map<String,Object> upload(String name,String mime,byte[] raw) {
        if (raw.length>5*1024*1024) throw new ApiFailure(413,"单个附件不能超过 5MB");
        if (raw.length==0) throw new ApiFailure(415,"附件不能为空");
        String suffix=name.substring(name.lastIndexOf('.')+1).toLowerCase(Locale.ROOT);
        String kind;
        if (IMAGES.contains(suffix)||Set.of("image/png","image/jpeg","image/gif","image/webp","image/bmp").contains(mime)) kind="image";
        else if (TEXT.contains(suffix)||mime.startsWith("text/")) kind="text";
        else throw new ApiFailure(415,"仅支持文本/配置/代码文件与 PNG/JPG/GIF/WebP/BMP 图片");
        if (kind.equals("text")) {
            try { StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(raw)); }
            catch (CharacterCodingException invalid) { throw new ApiFailure(415,"文本附件必须是 UTF-8 编码"); }
        }
        long id=insert("INSERT INTO assistant_attachments(name,mime,kind,size_bytes,path) VALUES (?,?,?,?,?)",name,mime,kind,raw.length,"");
        Path path=files.resolve(Long.toString(id));
        try { Files.write(path,raw,StandardOpenOption.CREATE_NEW); }
        catch (java.io.IOException failure) { throw new ApiFailure(500,"附件保存失败"); }
        org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization() {
            @Override public void afterCompletion(int status) {
                if (status!=STATUS_COMMITTED) try { Files.deleteIfExists(path); } catch (java.io.IOException ignored) { }
            }
        });
        db.update("UPDATE assistant_attachments SET path=? WHERE id=?",path.toString(),id);
        return Map.of("id",id,"name",name,"mime",mime,"kind",kind,"size_bytes",raw.length);
    }
    public List<Map<String,Object>> history(long id) {
        List<Map<String,Object>> result=new ArrayList<>();
        for (var row:messages(id)) {
            String role=row.get("role").toString(),text=row.get("content").toString();
            if (role.equals("user")) {
                @SuppressWarnings("unchecked") var attachments=(List<Map<String,Object>>)row.get("attachments");
                for (var item:attachments) {
                    String raw="";
                    if (item.get("kind").equals("text")) {
                        try { raw=clip(Files.readString(attachmentPath(attachment(((Number)item.get("id")).longValue())),StandardCharsets.UTF_8),2000); }
                        catch (Exception ignored) { }
                    }
                    text+="\n\n[附件 "+item.get("name")+"（"+item.get("mime")+"，"+(item.get("kind").equals("text")?item.get("size_bytes")+" 字节":"图片，本轮未重发")+"）]\n"+raw;
                }
                result.add(Map.of("role",role,"content",text));
            } else if (role.equals("assistant")) result.add(Map.of("role",role,"content",text));
            else {
                var trace=decode(text);
                if ("write_file".equals(trace.get("tool"))&&Objects.toString(trace.get("result"),"").contains("已写入"))
                    result.add(Map.of("role","user","content","（系统注记：用户已确认，文件已写入 "+trace.get("result")+"）"));
            }
        }
        return result;
    }
    public Map<String,Object> summary(long id) {
        var rows=db.queryForList("SELECT compressed_until,summary FROM assistant_summaries WHERE session_id=?",id);
        return rows.isEmpty()?Map.of():rows.getFirst();
    }
    public void saveSummary(long id,int count,String summary) {
        requireSession(id);
        db.update("INSERT INTO assistant_summaries(session_id,compressed_until,summary) VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET compressed_until=excluded.compressed_until,summary=excluded.summary,updated_at=datetime('now','localtime')",id,count,mask(summary));
    }
    @Transactional
    public long saveTurn(Long id,String message,List<Map<String,Object>> steps,String answer,List<Long> attachments,String workspace) {
        if (id==null) id=insert("INSERT INTO assistant_sessions(title,workspace) VALUES (?,?)",clip(mask(message.strip()),50),workspace.isBlank()?null:workspace);
        else requireSession(id);
        long messageId=insert("INSERT INTO assistant_messages(session_id,role,content,summary) VALUES (?,'user',?,?)",id,mask(message),mask(clip(message.strip(),24)+(message.strip().codePointCount(0,message.strip().length())>24?"…":"")));
        for (var step:steps) insert("INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'tool',?)",id,mask(encode(Map.of("tool",step.get("tool"),"args",step.getOrDefault("args",Map.of()),"result",clip(Objects.toString(step.get("result"),""),600)))));
        insert("INSERT INTO assistant_messages(session_id,role,content) VALUES (?,'assistant',?)",id,mask(answer));
        for (long file:attachments) {
            if (db.update("UPDATE assistant_attachments SET session_id=?,message_id=? WHERE id=? AND message_id IS NULL",id,messageId,file)!=1)
                throw new ApiFailure(400,"附件不存在或已使用，请重新添加");
        }
        db.update("UPDATE assistant_sessions SET updated_at=datetime('now','localtime') WHERE id=?",id);
        return id;
    }
    @Transactional
    public void delete(long id) {
        requireSession(id);
        var paths=db.queryForList("SELECT path FROM assistant_attachments WHERE session_id=?",String.class,id);
        db.update("DELETE FROM assistant_sessions WHERE id=?",id);
        db.update("DELETE FROM assistant_messages WHERE session_id=?",id);
        db.update("DELETE FROM assistant_summaries WHERE session_id=?",id);
        db.update("DELETE FROM assistant_attachments WHERE session_id=?",id);
        org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization() {
            @Override public void afterCommit() {
                for (String name:paths) try {
                    Path path=Path.of(name).toRealPath();
                    if (path.startsWith(files.toRealPath())) Files.deleteIfExists(path);
                } catch (java.io.IOException ignored) { }
            }
        });
    }
    public static String filename(String value) {
        String name=value.strip();
        if (name.isEmpty()||name.length()>120||!name.matches("[\\p{L}\\p{N}_.\\- ]+")||name.equals(".")||name.equals("..")||name.endsWith(".")||name.matches("(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\\..*)?"))
            throw new ApiFailure(400,"文件名仅支持中文/字母/数字/空格/点/下划线/连字符，且不能包含路径");
        return name;
    }
    @Transactional
    public synchronized String resolve(long session,String value,boolean accept) {
        String name=filename(value);
        for (var row:db.queryForList("SELECT id,content FROM assistant_messages WHERE session_id=? AND role='tool' ORDER BY id DESC",session)) {
            var trace=decode(row.get("content").toString());
            if (!"write_file".equals(trace.get("tool"))||!"等待用户确认".equals(trace.get("result"))) continue;
            if (!(trace.get("args") instanceof Map<?,?> args)||!name.equals(args.get("filename"))) continue;
            String outcome=accept?"用户已确认，已写入 agent_files/"+name:"用户已取消，未写入";
            if (accept) {
                Path temporary=null;
                try {
                    Path target=proposals.resolve(name);
                    if (Files.exists(target,LinkOption.NOFOLLOW_LINKS)&&!target.toRealPath().startsWith(proposals.toRealPath())) throw new java.io.IOException();
                    temporary=Files.createTempFile(proposals,"proposal-",".tmp");
                    Files.writeString(temporary,Objects.toString(args.get("content"),""),StandardCharsets.UTF_8);
                    Files.move(temporary,target,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
                } catch (java.io.IOException failure) { throw new ApiFailure(500,"文件提案写入失败"); }
                finally { if (temporary!=null) try { Files.deleteIfExists(temporary); } catch (java.io.IOException ignored) { } }
            }
            trace.put("result",outcome);
            db.update("UPDATE assistant_messages SET content=? WHERE id=?",encode(trace),row.get("id"));
            return outcome;
        }
        throw new ApiFailure(404,"没有待确认的文件提案");
    }
}
