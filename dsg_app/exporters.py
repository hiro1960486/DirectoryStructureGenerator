"""TXT, HTML, CSV and JSON exporters."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import ScanNode, ScanResult
from .version import APP_NAME, APP_VERSION, AUTHOR, UPDATED


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def iter_nodes(root: ScanNode) -> Iterator[ScanNode]:
    yield root
    for child in root.children:
        yield from iter_nodes(child)


def tree_lines(root: ScanNode) -> list[str]:
    lines = [root.name]

    def append(children: list[ScanNode], prefix: str) -> None:
        for index, node in enumerate(children):
            last = index == len(children) - 1
            lines.append(f"{prefix}{'└─ ' if last else '├─ '}{node.name}{'/' if node.is_dir else ''}")
            if node.children:
                append(node.children, prefix + ("   " if last else "│  "))

    append(root.children, "")
    return lines


def _metadata(result: ScanResult) -> list[str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return [
        f"生成元アプリ: {APP_NAME}", f"バージョン: Ver.{APP_VERSION}", f"更新日: {UPDATED}",
        f"作者: {AUTHOR}", f"生成日時: {now}", f"対象フォルダー: {result.source}",
        f"フォルダー数: {result.stats.folders}", f"ファイル数: {result.stats.files}",
        f"合計サイズ: {format_size(result.stats.total_size)}", f"除外数: {result.stats.excluded}",
    ]


def export_txt(result: ScanResult, destination: Path) -> None:
    content = "\n".join(_metadata(result) + ["", "-" * 64] + tree_lines(result.root)) + "\n"
    destination.write_text(content, encoding="utf-8-sig")


def _excel_safe(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(result: ScanResult, destination: Path) -> None:
    fields = ["type", "name", "relative_path", "full_path", "parent", "depth", "size", "modified", "symlink"]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for node in iter_nodes(result.root):
            row = {
                "type": "folder" if node.is_dir else "file", "name": node.name,
                "relative_path": str(node.relative_path), "full_path": str(node.path),
                "parent": str(node.path.parent), "depth": node.depth,
                "size": "" if node.is_dir else node.size,
                "modified": datetime.fromtimestamp(node.modified).strftime("%Y-%m-%d %H:%M:%S"),
                "symlink": node.is_symlink,
            }
            writer.writerow({key: _excel_safe(value) for key, value in row.items()})


def _node_to_dict(node: ScanNode) -> dict[str, object]:
    return {
        "name": node.name, "relative_path": str(node.relative_path),
        "type": "folder" if node.is_dir else "file", "depth": node.depth,
        "size": node.size, "modified": datetime.fromtimestamp(node.modified).isoformat(timespec="seconds"),
        "symlink": node.is_symlink,
        "children": [_node_to_dict(child) for child in node.children] if node.is_dir else [],
    }


def export_json(result: ScanResult, destination: Path) -> None:
    payload = {
        "application": {"name": APP_NAME, "version": APP_VERSION, "updated": UPDATED, "author": AUTHOR},
        "generated_at": datetime.now().isoformat(timespec="seconds"), "source": str(result.source),
        "statistics": {
            "folders": result.stats.folders, "files": result.stats.files,
            "total_size": result.stats.total_size, "excluded": result.stats.excluded,
            "errors": result.stats.errors, "elapsed_seconds": round(result.stats.elapsed_seconds, 3),
        },
        "filters": result.filters.to_dict(), "tree": _node_to_dict(result.root),
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_html(result: ScanResult, destination: Path) -> None:
    def render(node: ScanNode) -> str:
        label = html.escape(node.name)
        if node.is_dir:
            children = "".join(render(child) for child in node.children)
            return f'<li class="folder"><details open><summary>{label}</summary><ul>{children}</ul></details></li>'
        return f'<li class="file"><span>{label}</span><small>{html.escape(format_size(node.size))}</small></li>'

    meta = " · ".join(html.escape(item) for item in _metadata(result)[6:10])
    source = html.escape(str(result.source))
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    document = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(result.root.name)} - Directory Tree</title>
<style>
:root{{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#657089;--accent:#2563eb;--line:#dce3ef}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111827;--card:#182235;--text:#eef3ff;--muted:#a6b0c3;--accent:#60a5fa;--line:#334155}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,sans-serif}}
main{{max-width:1100px;margin:32px auto;padding:0 20px}} header{{background:linear-gradient(135deg,#2563eb,#06b6d4);color:#fff;padding:28px;border-radius:18px;box-shadow:0 12px 30px #0002}}
h1{{margin:0 0 6px;font-size:26px}} .source{{word-break:break-all;opacity:.9}} .card{{margin-top:18px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}} button,input{{border:1px solid var(--line);border-radius:9px;padding:9px 12px;background:var(--card);color:var(--text)}} input{{flex:1;min-width:220px}}
ul{{list-style:none;padding-left:22px}} li{{margin:3px 0}} summary{{cursor:pointer;font-weight:650}} summary::marker{{color:var(--accent)}} .file{{display:flex;gap:12px;justify-content:space-between;border-left:2px solid var(--line);padding-left:10px}} small{{color:var(--muted)}} .hidden{{display:none}}
</style></head><body><main><header><h1>📁 {html.escape(result.root.name)}</h1><div>{meta}</div><div class="source">{source}</div></header>
<section class="card"><div class="toolbar"><button onclick="toggle(true)">すべて開く</button><button onclick="toggle(false)">すべて閉じる</button><input id="q" placeholder="名前を検索" oninput="searchTree(this.value)"></div>
<ul id="tree">{render(result.root)}</ul></section><p><small>{APP_NAME} Ver.{APP_VERSION} · {generated}</small></p></main>
<script>function toggle(v){{document.querySelectorAll('details').forEach(x=>x.open=v)}}function searchTree(q){{q=q.toLowerCase();document.querySelectorAll('#tree li').forEach(x=>x.classList.toggle('hidden',q&&!x.textContent.toLowerCase().includes(q)));if(q)toggle(true)}}</script>
</body></html>"""
    destination.write_text(document, encoding="utf-8")


EXPORTERS = {"txt": export_txt, "html": export_html, "csv": export_csv, "json": export_json}


def export_selected(result: ScanResult, output_dir: Path, formats: list[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    root_name = result.root.name.strip()
    # A Windows drive root is represented by Path.name as "E:". Avoid
    # producing filenames such as "E__file_list.csv" after sanitizing it.
    if (
        len(root_name) >= 2 and root_name[1] == ":" and root_name[0].isalpha()
        and not root_name[2:].strip("\\\\/")
    ):
        root_name = f"{root_name[0].upper()}_drive"
    safe_name = "".join(char if char not in '<>:"/\\|?*' else "_" for char in root_name).strip(" _.") or "directory"
    suffixes = {"txt": "tree", "html": "index", "csv": "file_list", "json": "tree_data"}
    created: list[Path] = []
    for format_name in formats:
        if format_name not in EXPORTERS:
            continue
        path = output_dir / f"{safe_name}_{suffixes[format_name]}.{format_name}"
        EXPORTERS[format_name](result, path)
        created.append(path)
    return created
