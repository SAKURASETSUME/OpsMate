"""通过 AST 复制业务提示词，不导入应用或读取本机配置。"""
from __future__ import annotations
import ast
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root/"java-app"/"src"/"main"/"resources"/"prompts"
    target.mkdir(parents=True,exist_ok=True)
    sources = [("app/codegen/prompts.py","CODEGEN_SYSTEM_PROMPT","codegen.txt"),
               ("app/logs/analyze.py","LOG_ANALYZE_SYSTEM_PROMPT","logs.txt"),
               ("app/assistant/routes.py","ASSISTANT_SYSTEM_PROMPT","assistant.txt"),
               ("app/assistant/routes.py","ASSISTANT_DIRECT_PROMPT","assistant-direct.txt")]
    for source,variable,filename in sources:
        tree = ast.parse((root/source).read_text(encoding="utf-8"))
        values = [node.value.value for node in tree.body if isinstance(node,ast.Assign)
                  and any(isinstance(item,ast.Name) and item.id==variable for item in node.targets)
                  and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)]
        assert len(values)==1,variable
        (target/filename).write_text(values[0],encoding="utf-8")
        assert (target/filename).read_text(encoding="utf-8")==values[0]
    print("PASS: four business prompts copied exactly by AST")


if __name__=="__main__":
    main()
