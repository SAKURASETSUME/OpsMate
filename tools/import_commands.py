"""导入 linux-command 的 command/*.md，按 sparse clone → API → 内置数据降级。"""
from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

REPOSITORY_URL = "https://github.com/jaywcjlove/linux-command.git"
CONTENTS_API_URL = "https://api.github.com/repos/jaywcjlove/linux-command/contents/command"
MANUAL_ZIP_URL = "https://github.com/jaywcjlove/linux-command/archive/refs/heads/master.zip"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = PROJECT_ROOT / "data" / "commands"

BUILTIN_COMMANDS: dict[str, str] = {
    "ls": "列出目录内容",
    "cd": "切换当前工作目录",
    "cp": "复制文件或目录",
    "mv": "移动或重命名文件和目录",
    "rm": "删除文件或目录",
    "mkdir": "创建目录",
    "cat": "连接文件并输出内容",
    "grep": "按模式搜索文本内容",
    "sed": "流式编辑和转换文本",
    "awk": "按字段处理和分析文本",
    "find": "按条件查找文件和目录",
    "ps": "查看当前进程状态",
    "top": "实时查看系统进程和资源占用",
    "df": "查看磁盘文件系统空间使用情况",
    "du": "统计文件和目录的磁盘占用",
    "tar": "归档或解包文件",
    "systemctl": "管理 systemd 服务和系统状态",
    "journalctl": "查询 systemd 日志",
    "chmod": "修改文件权限",
    "chown": "修改文件所有者和用户组",
}


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """以 UTF-8 文本模式执行 git，不经 shell。"""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def _copy_markdown_files(source_dir: Path, target_dir: Path) -> int:
    """将源目录中的 markdown 复制到空的暂存目录。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for source_file in sorted(source_dir.glob("*.md"), key=lambda path: path.name.lower()):
        if not source_file.is_file():
            continue
        shutil.copy2(source_file, target_dir / source_file.name)
        count += 1
    return count


def _import_with_sparse_clone(staging_dir: Path) -> int:
    """只稀疏拉取上游 command 目录。"""
    _run_git(["--version"])
    with tempfile.TemporaryDirectory(prefix="opsmate-linux-command-") as temp_name:
        checkout_dir = Path(temp_name) / "linux-command"
        _run_git(
            [
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                REPOSITORY_URL,
                str(checkout_dir),
            ]
        )
        _run_git(["sparse-checkout", "set", "command"], cwd=checkout_dir)
        return _copy_markdown_files(checkout_dir / "command", staging_dir)


def _github_headers() -> dict[str, str]:
    """构造 GitHub API 请求头；可选读取环境变量令牌但不打印。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OpsMate-command-importer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _import_with_contents_api(staging_dir: Path) -> int:
    """在 API 剩余额度足够时逐文件获取 base64 内容。"""
    with httpx.Client(headers=_github_headers(), timeout=30.0, follow_redirects=True) as client:
        listing_response = client.get(CONTENTS_API_URL)
        listing_response.raise_for_status()
        listing = listing_response.json()
        if not isinstance(listing, list):
            raise RuntimeError("GitHub contents API 未返回文件列表")

        entries = sorted(
            (
                item
                for item in listing
                if isinstance(item, dict)
                and str(item.get("name", "")).lower().endswith(".md")
            ),
            key=lambda item: str(item["name"]).lower(),
        )
        remaining = int(listing_response.headers.get("X-RateLimit-Remaining", "0"))
        if remaining < len(entries):
            raise RuntimeError(
                f"GitHub API 剩余额度 {remaining}，不足以下载 {len(entries)} 个文件"
            )

        staging_dir.mkdir(parents=True, exist_ok=True)
        for item in entries:
            item_url = item.get("url")
            if not isinstance(item_url, str):
                raise RuntimeError(f"GitHub API 条目缺少 url：{item.get('name', 'unknown')}")
            item_response = client.get(item_url)
            item_response.raise_for_status()
            payload = item_response.json()
            if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
                raise RuntimeError(f"GitHub API 内容编码异常：{item['name']}")
            raw_bytes = base64.b64decode(payload["content"], validate=False)
            text = raw_bytes.decode("utf-8")
            (staging_dir / str(item["name"])).write_text(text, encoding="utf-8")
        return len(entries)


def _write_builtin_commands(staging_dir: Path) -> int:
    """写入 20 个常用命令的最小可用中文文档。"""
    staging_dir.mkdir(parents=True, exist_ok=True)
    for name, title in BUILTIN_COMMANDS.items():
        markdown = (
            f"{name}\n"
            "===\n"
            f"{title}\n\n"
            "### 语法\n\n"
            f"```bash\n{name} [选项] [参数]\n```\n\n"
            "### 说明\n\n"
            f"`{name}` 用于{title}。请在执行前通过 `--help` 或 `man` 核对当前系统版本支持的选项。\n"
        )
        (staging_dir / f"{name}.md").write_text(markdown, encoding="utf-8")
    return len(BUILTIN_COMMANDS)


def _replace_destination(staging_dir: Path, destination: Path) -> int:
    """在完整数据准备成功后替换目标目录中的命令文档。"""
    destination.mkdir(parents=True, exist_ok=True)
    for old_file in destination.glob("*.md"):
        old_file.unlink()
    return _copy_markdown_files(staging_dir, destination)


def import_commands(force: bool = False) -> tuple[int, str, list[str]]:
    """执行三级降级导入，返回数量、来源和失败摘要。"""
    existing_count = len(list(COMMANDS_DIR.glob("*.md")))
    if existing_count and not force:
        return existing_count, "existing", []

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="opsmate-command-staging-") as temp_name:
        base_staging = Path(temp_name)
        strategies = (
            ("sparse-clone", _import_with_sparse_clone),
            ("contents-api", _import_with_contents_api),
        )
        for source_name, strategy in strategies:
            staging_dir = base_staging / source_name
            try:
                count = strategy(staging_dir)
                if count >= 600:
                    return _replace_destination(staging_dir, COMMANDS_DIR), source_name, failures
                failures.append(f"{source_name}: 仅得到 {count} 个文档")
            except (OSError, RuntimeError, subprocess.SubprocessError, httpx.HTTPError) as exc:
                failures.append(f"{source_name}: {exc}")

        print(f"自动导入失败，可手动下载 {MANUAL_ZIP_URL}")
        print("解压后将 linux-command-master/command/ 下的 md 放入 data/commands/，再重新运行脚本。")
        builtin_dir = base_staging / "builtin"
        _write_builtin_commands(builtin_dir)
        return _replace_destination(builtin_dir, COMMANDS_DIR), "builtin", failures


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="导入 OpsMate 指令速查文档")
    parser.add_argument("--force", action="store_true", help="覆盖并重新导入现有命令文档")
    return parser


def main() -> int:
    """命令行入口。"""
    args = build_parser().parse_args()
    count, source, failures = import_commands(force=args.force)
    for failure in failures:
        print(f"降级记录：{failure}")
    print(f"数据来源：{source}")
    print(f"导入 {count} 个命令文档")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
