from pathlib import Path


OUT = Path(__file__).parent


DEFS = """
<defs>
  <style>
    .ui { font-family: 'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif; }
    .serif { font-family: 'Songti SC','STSong','Noto Serif CJK SC',serif; }
    .ink { fill: #3C322E; } .muted { fill: #6F625B; }
    .icon { fill: none; stroke: currentColor; stroke-width: 1.85; stroke-linecap: round; stroke-linejoin: round; }
  </style>
  <symbol id="panel" viewBox="0 0 24 24"><rect class="icon" x="3" y="4" width="18" height="16" rx="2"/><path class="icon" d="M9 4v16"/></symbol>
  <symbol id="note" viewBox="0 0 24 24"><path class="icon" d="M6 3h9l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM15 3v5h4M8 12h8M8 16h6"/></symbol>
  <symbol id="spark" viewBox="0 0 24 24"><path class="icon" d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z"/></symbol>
  <symbol id="calendar" viewBox="0 0 24 24"><rect class="icon" x="3" y="5" width="18" height="16" rx="2"/><path class="icon" d="M7 3v4m10-4v4M3 10h18"/></symbol>
  <symbol id="bell" viewBox="0 0 24 24"><path class="icon" d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 9h18c0-1-3-2-3-9zM10 21h4"/></symbol>
  <symbol id="book" viewBox="0 0 24 24"><path class="icon" d="M4 4h7a3 3 0 0 1 3 3v13H7a3 3 0 0 0-3 1zm16 0h-3a3 3 0 0 0-3 3v13h3a3 3 0 0 1 3 1z"/></symbol>
  <symbol id="search" viewBox="0 0 24 24"><circle class="icon" cx="10.7" cy="10.7" r="6.4"/><path class="icon" d="m16 16 4.3 4.3"/></symbol>
  <symbol id="plus" viewBox="0 0 24 24"><path class="icon" d="M12 5v14M5 12h14"/></symbol>
  <symbol id="grid" viewBox="0 0 24 24"><rect class="icon" x="3" y="3" width="7" height="7" rx="1.5"/><rect class="icon" x="14" y="3" width="7" height="7" rx="1.5"/><rect class="icon" x="3" y="14" width="7" height="7" rx="1.5"/><rect class="icon" x="14" y="14" width="7" height="7" rx="1.5"/></symbol>
  <symbol id="list" viewBox="0 0 24 24"><path class="icon" d="M8 5h13M8 12h13M8 19h13M3 5h.01M3 12h.01M3 19h.01"/></symbol>
  <symbol id="arrow" viewBox="0 0 24 24"><path class="icon" d="M4 12h15m-6-6 6 6-6 6"/></symbol>
</defs>
"""


def draw(expanded: bool) -> str:
    side = 220 if expanded else 72
    x = 320 if expanded else 246
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000" role="img" aria-labelledby="title desc">',
        f'<title id="title">淡枫叶色笔记首页：{"展开" if expanded else "收起"}导航</title>',
        '<desc id="desc">浅色文雅风的笔记首页，保留继续写作和少量最近笔记卡片，侧栏可折叠。</desc>',
        DEFS,
        '<rect width="1600" height="1000" fill="#FCFAF7"/>',
        f'<rect width="{side}" height="1000" fill="#F5F0EA"/>',
        f'<path d="M{side-.5} 0v1000" stroke="#E9DFD8"/>',
    ]

    def add(tag: str) -> None:
        parts.append(tag)

    if expanded:
        add('<rect x="25" y="29" width="37" height="37" rx="11" fill="#AA6A56"/>')
        add('<text x="43.5" y="55" class="ui" fill="#FFFFFF" font-size="21" font-weight="700" text-anchor="middle">N</text>')
        add('<text x="75" y="55" class="ui ink" font-size="16" font-weight="650">个人知识库</text>')
        nav = [(144, "note", "笔记", True), (204, "spark", "AI 助手", False), (264, "calendar", "日历", False), (324, "bell", "提醒", False)]
        for y, icon, label, active in nav:
            if active:
                add(f'<rect x="14" y="{y-17}" width="192" height="47" rx="11" fill="#EBD9CE"/>')
            add(f'<use href="#{icon}" x="31" y="{y-5}" width="21" height="21" color="{"#965B48" if active else "#9C8D82"}"/>')
            add(f'<text x="67" y="{y+12}" class="ui" fill="{"#744634" if active else "#625750"}" font-size="14" font-weight="{"650" if active else "400"}">{label}</text>')
        add('<line x1="25" y1="391" x2="195" y2="391" stroke="#E5DAD2"/>')
        add('<text x="31" y="431" class="ui muted" font-size="12" font-weight="600">笔记本</text>')
        add('<use href="#plus" x="178" y="412" width="20" height="20" color="#A48C7E"/>')
        for y, label in [(465, "随手记"), (515, "课程学习"), (565, "项目资料")]:
            add(f'<use href="#book" x="33" y="{y-16}" width="18" height="18" color="#AD9D91"/>')
            add(f'<text x="67" y="{y}" class="ui ink" font-size="13">{label}</text>')
        add('<line x1="25" y1="918" x2="195" y2="918" stroke="#E5DAD2"/>')
        add('<circle cx="45" cy="958" r="17" fill="#E4CFC3"/>')
        add('<text x="45" y="963" class="ui" fill="#7F4D3C" font-size="13" font-weight="650" text-anchor="middle">我</text>')
        add('<text x="74" y="963" class="ui ink" font-size="12">我的空间</text>')
    else:
        add('<rect x="18" y="29" width="36" height="36" rx="11" fill="#AA6A56"/>')
        add('<text x="36" y="54" class="ui" fill="#FFFFFF" font-size="21" font-weight="700" text-anchor="middle">N</text>')
        for y, icon, active in [(144, "note", True), (204, "spark", False), (264, "calendar", False), (324, "bell", False)]:
            if active:
                add(f'<rect x="9" y="{y-17}" width="54" height="47" rx="11" fill="#EBD9CE"/>')
            add(f'<use href="#{icon}" x="25" y="{y-5}" width="22" height="22" color="{"#965B48" if active else "#9C8D82"}"/>')
        add('<line x1="17" y1="391" x2="55" y2="391" stroke="#E5DAD2"/>')
        add('<use href="#book" x="25" y="416" width="22" height="22" color="#AD9D91"/>')
        add('<circle cx="36" cy="958" r="17" fill="#E4CFC3"/>')
        add('<text x="36" y="963" class="ui" fill="#7F4D3C" font-size="13" font-weight="650" text-anchor="middle">我</text>')

    # 主标题与紧凑工具栏。
    add(f'<use href="#panel" x="{x}" y="105" width="22" height="22" color="#9A8376"/>')
    add(f'<text x="{x+48}" y="143" class="serif ink" font-size="39" font-weight="650">笔记</text>')
    add(f'<rect x="{x+773}" y="104" width="38" height="38" rx="9" fill="#F2E8E1"/>')
    add(f'<use href="#grid" x="{x+781}" y="112" width="22" height="22" color="#976250"/>')
    add(f'<use href="#list" x="{x+823}" y="112" width="22" height="22" color="#A9978D"/>')
    add(f'<rect x="{x+866}" y="101" width="196" height="44" rx="10" fill="#FFFFFF" stroke="#E8DDD4"/>')
    add(f'<use href="#search" x="{x+881}" y="112" width="20" height="20" color="#9E8B7F"/>')
    add(f'<text x="{x+911}" y="130" class="ui muted" font-size="13">搜索笔记</text>')
    add(f'<rect x="{x+1082}" y="101" width="98" height="44" rx="10" fill="#A56450"/>')
    add(f'<use href="#plus" x="{x+1093}" y="112" width="20" height="20" color="#FFFFFF"/>')
    add(f'<text x="{x+1119}" y="129" class="ui" fill="#FFFFFF" font-size="13" font-weight="650">新建</text>')

    # 延续书写仍是沿用上一版设计的核心内容。
    add(f'<rect x="{x}" y="211" width="1180" height="188" rx="17" fill="#F5E9E1" stroke="#EBD9CF"/>')
    add(f'<rect x="{x+28}" y="239" width="4" height="132" rx="2" fill="#BB7965"/>')
    add(f'<text x="{x+57}" y="257" class="ui" fill="#985F4D" font-size="13" font-weight="650">继续写作</text>')
    add(f'<text x="{x+57}" y="313" class="serif ink" font-size="28" font-weight="650">个人知识管理系统 · 需求梳理</text>')
    add(f'<text x="{x+57}" y="365" class="ui muted" font-size="12">今天 09:42</text>')
    add(f'<rect x="{x+1096}" y="315" width="52" height="52" rx="12" fill="#FFFAF6" stroke="#E6CFC1"/>')
    add(f'<use href="#arrow" x="{x+1111}" y="330" width="22" height="22" color="#A56450"/>')

    add(f'<text x="{x}" y="471" class="serif ink" font-size="24" font-weight="650">最近笔记</text>')
    add(f'<text x="{x+1180}" y="468" class="ui muted" font-size="12" text-anchor="end">查看全部  →</text>')
    notes = [
        ("第二大脑的几点思考", "今天"),
        ("信息检索课程", "昨天"),
        ("毕业设计 · 接口与数据结构", "9 月 30 日"),
    ]
    for i, (title, date) in enumerate(notes):
        cx = x + i * 400
        add(f'<rect x="{cx}" y="501" width="380" height="322" rx="17" fill="#FFFEFC" stroke="#E9DFD7"/>')
        add(f'<use href="#note" x="{cx+27}" y="528" width="22" height="22" color="#B18470"/>')
        add(f'<line x1="{cx+27}" y1="739" x2="{cx+353}" y2="739" stroke="#EFE7E1"/>')
        add(f'<text x="{cx+27}" y="708" class="serif ink" font-size="21" font-weight="630">{title}</text>')
        add(f'<text x="{cx+27}" y="782" class="ui muted" font-size="12">{date}</text>')

    parts.append('</svg>')
    return '\n'.join(parts)


if __name__ == '__main__':
    (OUT / 'home-notes-maple.svg').write_text(draw(True), encoding='utf-8')
    (OUT / 'home-notes-maple-collapsed.svg').write_text(draw(False), encoding='utf-8')
