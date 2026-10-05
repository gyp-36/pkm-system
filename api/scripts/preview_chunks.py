"""Print the chunks produced for a Markdown, DOCX, XLSX, or PDF file."""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from pathlib import Path

from app.knowledge.chunking import segment_note


@dataclass(frozen=True)
class TextBlock:
    start_offset: int
    end_offset: int
    locator: dict


def collect_preview(path: Path, title: str | None = None):
    extension = path.suffix.lower().lstrip(".")
    if extension not in {"md", "docx", "xlsx", "pdf"}:
        raise ValueError(f"暂不支持预览 .{extension or '(无扩展名)'}；支持 md、docx、xlsx、pdf。")

    content = path.read_bytes()
    if extension == "md":
        body = content.decode("utf-8-sig")[:1_000_000]
        raw_blocks = [(0, len(body), {"kind": "markdown"})] if body else []
    else:
        from app.knowledge.m3 import extract_text

        body, raw_blocks = extract_text(extension, content)
    if not body.strip():
        raise ValueError("文件没有提取到文本。扫描版 PDF 和图片需要先经过视觉识别流程。")

    blocks = [TextBlock(start, end, locator) for start, end, locator in raw_blocks]
    note_title = title or path.stem
    segments = segment_note(note_title, body, blocks)
    return note_title, body, segments


def render_preview(path: Path, title: str | None = None) -> str:
    note_title, body, segments = collect_preview(path, title)
    output = [f"文件：{path}", f"标题：{note_title}", f"正文长度：{len(body)} 字符", f"切片数量：{len(segments)}", ""]
    for index, segment in enumerate(segments, start=1):
        location = json.dumps(segment.location or {}, ensure_ascii=False, sort_keys=True)
        output.extend(
            [
                f"{'=' * 24} 切片 {index} {'=' * 24}",
                f"source={segment.source.name.lower()} | offset=[{segment.start}, {segment.end}) | length={len(segment.content)}",
                f"location={location}",
                f"embedding_context={segment.context_prefix or '(无)'}",
                segment.content,
                "",
            ]
        )
    return "\n".join(output)


def render_html_preview(path: Path, title: str | None = None) -> str:
    note_title, body, segments = collect_preview(path, title)
    cards = []
    for index, segment in enumerate(segments, start=1):
        location = json.dumps(segment.location or {}, ensure_ascii=False, indent=2, sort_keys=True)
        heading_path = " / ".join((segment.location or {}).get("heading_path", []))
        cards.append(f"""
        <article class="chunk-card">
          <header class="chunk-header">
            <div><span class="chunk-number">切片 {index:02d}</span><span class="kind">{html.escape((segment.location or {}).get('kind', segment.source.name.lower()))}</span></div>
            <span class="length">{len(segment.content)} 字符</span>
          </header>
          <div class="meta">偏移 [{segment.start}, {segment.end}){f' · {html.escape(heading_path)}' if heading_path else ''}</div>
          <pre class="content">{html.escape(segment.content)}</pre>
          <details><summary>位置元数据</summary><pre class="location">{html.escape(location)}</pre></details>
        </article>""")

    escaped_title = html.escape(note_title)
    escaped_path = html.escape(str(path))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>切片预览 · {escaped_title}</title>
  <style>
    :root {{ color-scheme: light; --ink:#20242b; --muted:#68707d; --line:#e5e8ed; --paper:#f5f6f8; --accent:#5368d8; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(100% - 32px, 960px); margin:40px auto 72px; }}
    .hero {{ padding:28px 30px; background:#fff; border:1px solid var(--line); border-radius:16px; box-shadow:0 8px 28px #18233a0a; }}
    .eyebrow {{ color:var(--accent); font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ margin:8px 0 12px; font-size:26px; line-height:1.3; }}
    .file {{ color:var(--muted); overflow-wrap:anywhere; font-size:13px; }}
    .stats {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:20px; }}
    .stat {{ padding:7px 11px; color:#414958; background:#f1f3f7; border-radius:8px; font-size:13px; }}
    h2 {{ margin:30px 2px 12px; font-size:17px; }}
    .chunk-card {{ margin:12px 0; padding:18px 20px; background:#fff; border:1px solid var(--line); border-radius:12px; }}
    .chunk-header {{ display:flex; justify-content:space-between; gap:12px; align-items:center; }}
    .chunk-number {{ font-weight:700; }}
    .kind {{ margin-left:9px; padding:2px 8px; color:#4857ae; background:#eef0ff; border-radius:99px; font-size:12px; }}
    .length,.meta {{ color:var(--muted); font-size:12px; }}
    .meta {{ margin-top:5px; overflow-wrap:anywhere; }}
    .content {{ margin:15px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; font:14px/1.75 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    details {{ margin-top:12px; color:var(--muted); font-size:12px; }}
    summary {{ cursor:pointer; }}
    .location {{ margin:8px 0 0; padding:10px; overflow:auto; background:#f7f8fa; border-radius:8px; color:#4d5664; font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    @media(max-width:600px) {{ main {{ width:min(100% - 20px, 960px); margin-top:16px; }} .hero {{ padding:20px; }} .chunk-card {{ padding:15px; }} h1 {{ font-size:22px; }} }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="eyebrow">Knowledge chunk preview</div>
      <h1>{escaped_title}</h1>
      <div class="file">{escaped_path}</div>
      <div class="stats"><span class="stat">正文 {len(body)} 字符</span><span class="stat">共 {len(segments)} 个切片</span><span class="stat">每片上限 480 字符</span></div>
    </section>
    <h2>切片内容</h2>
    {''.join(cards)}
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="预览知识库文件抽取后的切片内容，不连接数据库或调用向量模型。")
    parser.add_argument("file", type=Path, help="待预览文件路径（md/docx/xlsx/pdf）")
    parser.add_argument("--title", help="覆盖默认标题；默认使用文件名")
    parser.add_argument("--output", type=Path, help="将预览结果另存为文件；使用 .html 扩展名生成网页")
    args = parser.parse_args()

    if not args.file.is_file():
        parser.error(f"文件不存在：{args.file}")

    try:
        render = render_html_preview if args.output and args.output.suffix.lower() == ".html" else render_preview
        preview = render(args.file, args.title)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    if args.output:
        args.output.write_text(preview, encoding="utf-8")
        print(f"预览已写入：{args.output}")
    else:
        print(preview)


if __name__ == "__main__":
    main()
