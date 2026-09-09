from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "PROJECT_DOCUMENTATION_COMPLETE.md"


@dataclass(frozen=True)
class Chapter:
    part_number: int
    part_title: str
    chapter_number: str
    chapter_title: str
    source_path: str

    @property
    def anchor(self) -> str:
        return "chapter-" + self.chapter_number.replace(".", "-")


CHAPTERS = [
    Chapter(1, "项目入口与快速开始", "1.1", "中文项目总览", "README.zh-CN.md"),
    Chapter(1, "项目入口与快速开始", "1.2", "English Project Overview", "README.md"),
    Chapter(2, "文档导航与阅读地图", "2.1", "文档索引与推荐阅读顺序", "docs/README.md"),
    Chapter(2, "文档导航与阅读地图", "2.2", "核心技术全景与项目学习手册", "docs/PROJECT_LEARNING_MANUAL.md"),
    Chapter(3, "总体架构与多 Agent 系统", "3.1", "系统总体架构", "docs/architecture.md"),
    Chapter(3, "总体架构与多 Agent 系统", "3.2", "医疗多 Agent 系统设计", "docs/medical-multi-agent-design.md"),
    Chapter(4, "医学知识、检索与训练数据", "4.1", "医学知识检索与证据融合", "docs/medical-knowledge-retrieval-design.md"),
    Chapter(4, "医学知识、检索与训练数据", "4.2", "中国临床知识治理与合规入库", "docs/chinese-medical-knowledge-governance.md"),
    Chapter(4, "医学知识、检索与训练数据", "4.3", "中文医疗 NLP 与 Agent Benchmark", "docs/chinese-medical-benchmarks.md"),
    Chapter(4, "医学知识、检索与训练数据", "4.4", "医学微调数据说明", "data/medical_finetune/README.md"),
    Chapter(5, "状态、上下文与随访闭环", "5.1", "三层记忆系统设计", "docs/memory-system-design.md"),
    Chapter(5, "状态、上下文与随访闭环", "5.2", "Token 与上下文预算优化", "docs/token-optimization-design.md"),
    Chapter(5, "状态、上下文与随访闭环", "5.3", "回诊与随访系统设计", "docs/follow-up-system-design.md"),
    Chapter(6, "安全、评测与可靠性", "6.1", "安全防御体系", "docs/security-defense-design.md"),
    Chapter(6, "安全、评测与可靠性", "6.2", "统一评测方法", "docs/evaluation-methodology.md"),
    Chapter(7, "工程实现、基线与展示", "7.1", "LangChain 与 LangGraph 实现", "docs/langchain-langgraph-implementation.md"),
    Chapter(7, "工程实现、基线与展示", "7.2", "MySQL 部署与迁移", "docs/mysql-deployment.md"),
    Chapter(7, "工程实现、基线与展示", "7.3", "RAGFlow 基线方案", "docs/ragflow-baseline.md"),
    Chapter(7, "工程实现、基线与展示", "7.4", "Web 可视化控制台设计", "docs/web-visualization-design.md"),
    Chapter(7, "工程实现、基线与展示", "7.5", "Program MVP 运行说明", "program/README.md"),
    Chapter(8, "简历与面试材料", "8.1", "Interview Pack", "docs/interview-pack.md"),
    Chapter(8, "简历与面试材料", "8.2", "项目面试官问答", "interview.md"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge all project Markdown documents into one structured handbook.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output_path = args.out.resolve()
    validate_chapter_inventory(output_path)
    content = build_merged_document(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    print(f"Merged {len(CHAPTERS)} Markdown files")
    print(f"Output: {output_path}")
    return 0


def validate_chapter_inventory(output_path: Path) -> None:
    configured = {chapter.source_path for chapter in CHAPTERS}
    discovered = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in PROJECT_ROOT.rglob("*.md")
        if path.resolve() != output_path and not is_generated_or_ignored(path)
    }
    missing = sorted(configured - discovered)
    unlisted = sorted(discovered - configured)
    if missing or unlisted:
        details = []
        if missing:
            details.append("missing configured files: " + ", ".join(missing))
        if unlisted:
            details.append("unlisted Markdown files: " + ", ".join(unlisted))
        raise SystemExit("Markdown inventory mismatch; update CHAPTERS first. " + "; ".join(details))


def is_generated_or_ignored(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    return (
        relative == "docs/PROJECT_DOCUMENTATION_COMPLETE.md"
        or relative == "user_docs/PROJECT_DOCUMENTATION_COMPLETE.md"
        or relative.startswith("docs/modules/")
        or relative.startswith((".agents/", ".github/", ".specify/", "develop_kit/", ".cache/", "frontend/"))
        or relative.startswith("data/medical_finetune/raw/")
        or relative.startswith("data/benchmarks/")
        or relative.startswith("reports/")
        or any(
            part in {".venv", "venv", "site-packages", "node_modules", ".git", ".pytest_cache"} for part in path.parts
        )
    )


def build_merged_document(output_path: Path) -> str:
    lines = [
        "# Agentic RAG Eval 完整项目文档",
        "",
        "> 本文件由 `program/merge_markdown_docs.py` 自动合并。源文档仍是日常维护入口；源文档更新后请重新运行合并脚本。",
        "",
        "## 合并范围",
        "",
        "- 项目根目录：`.`",
        f"- Markdown 文件数：`{len(CHAPTERS)}`",
        "- 组织方式：按目录职责重排为 8 编，并保留每章的来源目录和原文件名。",
        "",
        "## 总目录",
        "",
    ]
    lines.extend(build_toc())
    lines.extend(["", "## 章节、目录与原文件映射", ""])
    lines.extend(build_mapping_table())

    current_part = 0
    for chapter in CHAPTERS:
        if chapter.part_number != current_part:
            current_part = chapter.part_number
            lines.extend(
                [
                    "",
                    "---",
                    "",
                    f'<a id="part-{current_part}"></a>',
                    f"# 第{chinese_number(current_part)}编　{chapter.part_title}",
                    "",
                ]
            )
        source = PROJECT_ROOT / chapter.source_path
        source_directory = source.parent.relative_to(PROJECT_ROOT).as_posix() or "."
        source_link = relative_link(output_path.parent, source)
        lines.extend(
            [
                f'<a id="{chapter.anchor}"></a>',
                f"## 第 {chapter.chapter_number} 章　{chapter.chapter_title}",
                "",
                f"> 来源目录：`{source_directory}`  ",
                f"> 原文件：[{chapter.source_path}]({source_link})",
                "",
            ]
        )
        source_text = source.read_text(encoding="utf-8-sig")
        lines.extend(transform_source_markdown(source_text, source.parent, output_path.parent))

    lines.append("")
    return "\n".join(lines)


def build_toc() -> list[str]:
    lines: list[str] = []
    current_part = 0
    for chapter in CHAPTERS:
        if chapter.part_number != current_part:
            current_part = chapter.part_number
            lines.append(f"- [第{chinese_number(current_part)}编　{chapter.part_title}](#part-{current_part})")
        lines.append(f"  - [{chapter.chapter_number}　{chapter.chapter_title}](#{chapter.anchor})")
    return lines


def build_mapping_table() -> list[str]:
    lines = [
        "| 章节 | 章节名称 | 来源目录 | 原文件 |",
        "| --- | --- | --- | --- |",
    ]
    for chapter in CHAPTERS:
        source = Path(chapter.source_path)
        directory = source.parent.as_posix() if source.parent.as_posix() != "." else "根目录"
        lines.append(f"| {chapter.chapter_number} | {chapter.chapter_title} | `{directory}` | `{source.name}` |")
    return lines


def transform_source_markdown(
    content: str, source_directory: Path, output_directory: Path
) -> list[str]:
    transformed: list[str] = []
    in_fence = False
    for line in content.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            transformed.append(line)
            continue
        if not in_fence:
            heading = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading:
                level = min(len(heading.group(1)) + 2, 6)
                line = "#" * level + " " + heading.group(2)
            line = rewrite_local_markdown_links(line, source_directory, output_directory)
        transformed.append(line)
    return transformed


def rewrite_local_markdown_links(
    line: str, source_directory: Path, output_directory: Path
) -> str:
    def replace(match: re.Match[str]) -> str:
        label, target, title = match.groups()
        path, separator, fragment = target.partition("#")
        if not path or path.startswith(("/", "\\")) or "://" in path or path.startswith("mailto:"):
            return match.group(0)

        resolved_target = (source_directory / path).resolve()
        try:
            resolved_target.relative_to(PROJECT_ROOT)
        except ValueError:
            return match.group(0)
        if not resolved_target.exists():
            return match.group(0)

        rewritten_target = relative_link(output_directory, resolved_target)
        if separator:
            rewritten_target += separator + fragment
        return f"[{label}]({rewritten_target}{title or ''})"

    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)", replace, line)


def relative_link(from_directory: Path, target: Path) -> str:
    try:
        return target.relative_to(from_directory).as_posix()
    except ValueError:
        return Path("..", target.relative_to(PROJECT_ROOT)).as_posix()


def chinese_number(number: int) -> str:
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}[number]


if __name__ == "__main__":
    raise SystemExit(main())