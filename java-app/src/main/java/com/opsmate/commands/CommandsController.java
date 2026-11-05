package com.opsmate.commands;

import com.opsmate.infrastructure.ApiFailure;
import com.opsmate.infrastructure.RuntimePaths;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/commands")
class CommandsController {
    private record Command(String name, String title, Path file) {}
    private final List<Command> commands;

    CommandsController(RuntimePaths paths) throws java.io.IOException {
        Path directory = paths.knowledge().resolve("commands");
        List<Command> records = new ArrayList<>();
        if (Files.isDirectory(directory)) {
            try (var files = Files.list(directory)) {
                for (Path file : files.filter(p -> p.toString().endsWith(".md")).sorted().toList()) {
                    String text = Files.readString(file,StandardCharsets.UTF_8).replaceFirst("^\\uFEFF","");
                    String[] lines = text.split("\\R");
                    int start = lines.length >= 2 && lines[1].strip().equals("===") ? 2 : 1;
                    String title = "暂无简介";
                    for (int i = start; i < lines.length; i++) {
                        String candidate = lines[i].strip();
                        if (!candidate.isEmpty() && !candidate.startsWith("#")) {
                            title = candidate.substring(0,Math.min(candidate.length(),120));
                            break;
                        }
                    }
                    records.add(new Command(file.getFileName().toString().replaceFirst("\\.md$",""),title,file));
                }
            }
        }
        records.sort(Comparator.comparing(c -> c.name().toLowerCase(Locale.ROOT)));
        commands = List.copyOf(records);
    }

    private int rank(Command command, String query) {
        String name = command.name().toLowerCase(Locale.ROOT);
        if (query.isEmpty() || name.startsWith(query)) return 0;
        if (name.contains(query)) return 1;
        if (command.title().toLowerCase(Locale.ROOT).contains(query)) return 2;
        return 3;
    }

    @GetMapping
    Map<String,Object> search(@RequestParam(defaultValue="") String q,
                              @RequestParam(defaultValue="20") int limit) {
        if (limit < 1 || limit > 2000) throw new ApiFailure(422,"limit 必须在 1–2000 之间");
        String query = q.strip().toLowerCase(Locale.ROOT);
        var matches = commands.stream().filter(c -> rank(c,query) < 3)
            .sorted(Comparator.comparingInt((Command c) -> rank(c,query))
                .thenComparing(c -> c.name().toLowerCase(Locale.ROOT))).toList();
        return Map.of("total",matches.size(),"items",matches.stream().limit(limit)
            .map(c -> Map.of("name",c.name(),"title",c.title())).toList());
    }

    @GetMapping("/{name}")
    Map<String,String> detail(@PathVariable String name) throws java.io.IOException {
        Command command = commands.stream().filter(c -> c.name().equalsIgnoreCase(name)).findFirst()
            .orElseThrow(() -> new ApiFailure(404,"命令不存在"));
        String markdown = Files.readString(command.file(),StandardCharsets.UTF_8)
            .replace("\r\n","\n").replace("\r","\n")
            .replaceAll("(?i)<!--rehype:[^>]*-->","");
        return Map.of("name",command.name(),"title",command.title(),"markdown",markdown);
    }
}
