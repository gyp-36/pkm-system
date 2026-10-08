from pathlib import Path

from build_maple_mockups import DEFS


OUT = Path(__file__).parent
EXTRA = """
<defs>
  <symbol id="send" viewBox="0 0 24 24"><path class="icon" d="m3 20 18-8L3 4l3 7 8 1-8 1z"/></symbol>
  <symbol id="more" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/></symbol>
</defs>
"""


def rect(x, y, w, h, fill, radius=0, stroke=None):
    border = f' stroke="{stroke}"' if stroke else ''
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"{border}/>'


def text(x, y, value, size=14, cls='ui ink', weight=None, fill=None, anchor=None):
    attrs = f' font-weight="{weight}"' if weight else ''
    attrs += f' fill="{fill}"' if fill else ''
    attrs += f' text-anchor="{anchor}"' if anchor else ''
    return f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}"{attrs}>{value}</text>'


def icon(name, x, y, color, size=22):
    return f'<use href="#{name}" x="{x}" y="{y}" width="{size}" height="{size}" color="{color}"/>'


def begin(name):
    return [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000" role="img" aria-labelledby="title desc">',
        f'<title id="title">{name}</title>',
        '<desc id="desc">默认图标导航，笔记本和 AI 对话可显示或收起列表栏。</desc>',
        DEFS,
        EXTRA,
        rect(0, 0, 1600, 1000, '#FCFAF7'),
        rect(0, 0, 76, 1000, '#F4EEE8'),
        '<line x1="75.5" y1="0" x2="75.5" y2="1000" stroke="#E9DFD8"/>',
        rect(19, 28, 38, 38, '#965540', 11),
        text(38, 55, 'N', 21, 'ui', 700, '#FFFFFF', 'middle'),
    ]


def rail(parts, active):
    items = [('note', 150), ('book', 216), ('spark', 282), ('calendar', 348), ('bell', 414)]
    for name, y in items:
        if name == active:
            parts.append(rect(10, y - 12, 56, 48, '#EAD9CF', 11))
        parts.append(icon(name, 27, y, '#965B48' if name == active else '#9C8D82'))
    parts += [
        '<line x1="19" y1="488" x2="57" y2="488" stroke="#E5DAD2"/>',
        icon('more', 27, 508, '#A18D80'),
        '<circle cx="38" cy="958" r="18" fill="#E4CFC3"/>',
        text(38, 963, '我', 13, 'ui', 650, '#7F4D3C', 'middle'),
    ]


def pane(parts, kind):
    parts += [
        rect(76, 0, 245, 1000, '#F8F3EE'),
        '<line x1="320.5" y1="0" x2="320.5" y2="1000" stroke="#E9DFD8"/>',
        text(104, 111, '笔记本' if kind == 'notebooks' else '对话', 23, 'serif ink', 650),
        icon('panel', 275, 88, '#9C8274', 20),
    ]
    if kind == 'notebooks':
        entries = [('全部笔记', 165), ('随手记', 219), ('课程学习', 273), ('项目资料', 327)]
        for label, y in entries:
            selected = label == '课程学习'
            if selected:
                parts.append(rect(89, y - 23, 219, 44, '#EAD9CF', 9))
            parts.append(icon('book' if label != '全部笔记' else 'note', 105, y - 12, '#965B48' if selected else '#AA9689', 18))
            parts.append(text(138, y + 2, label, 13, 'ui', 650 if selected else None, '#744634' if selected else '#665B54'))
    else:
        parts.append(rect(92, 146, 212, 43, '#965540', 9))
        parts.append(icon('plus', 111, 157, '#FFFFFF', 20))
        parts.append(text(142, 174, '新对话', 13, 'ui', 650, '#FFFFFF'))
        for label, y in [('知识管理系统', 228), ('检索方法整理', 281), ('本周回顾', 334)]:
            if y == 228:
                parts.append(rect(92, y - 25, 212, 44, '#EAD9CF', 9))
            parts.append(text(109, y + 1, label, 13, 'ui', 650 if y == 228 else None, '#744634' if y == 228 else '#665B54'))


def toolbar(parts, x, title, with_toggle=False, new_label='新建'):
    heading_x = x + 48 if with_toggle else x
    if with_toggle:
        parts.append(icon('panel', x, 105, '#9A8376'))
    parts += [
        text(heading_x, 143, title, 39, 'serif ink', 650),
        rect(x + 773, 104, 38, 38, '#F2E8E1', 9),
        icon('grid', x + 781, 112, '#976250'),
        icon('list', x + 823, 112, '#A9978D'),
        rect(x + 866, 101, 196, 44, '#FFFFFF', 10, '#E8DDD4'),
        icon('search', x + 881, 112, '#9E8B7F', 20),
        text(x + 911, 130, '搜索笔记', 13, 'ui muted'),
        rect(x + 1082, 101, 98, 44, '#965540', 10),
        icon('plus', x + 1093, 112, '#FFFFFF', 20),
        text(x + 1119, 129, new_label, 13, 'ui', 650, '#FFFFFF'),
    ]


def note_card(parts, x, y, title, date, selected=False):
    parts += [
        rect(x, y, 380, 313, '#F5E9E1' if selected else '#FFFEFC', 17, '#EBD9CF' if selected else '#E9DFD7'),
        icon('note', x + 27, y + 27, '#A96E5B' if selected else '#B18470'),
        text(x + 27, y + 205, title, 20, 'serif ink', 630),
        f'<line x1="{x+27}" y1="{y+234}" x2="{x+353}" y2="{y+234}" stroke="#EFE7E1"/>',
        text(x + 27, y + 273, date, 12, 'ui muted'),
    ]


def notes_home():
    parts = begin('笔记首页')
    rail(parts, 'note')
    x = 247
    toolbar(parts, x, '笔记')
    parts += [
        rect(x, 211, 1180, 188, '#F5E9E1', 17, '#EBD9CF'),
        rect(x + 28, 239, 4, 132, '#BB7965', 2),
        text(x + 57, 257, '继续写作', 13, 'ui', 650, '#985F4D'),
        text(x + 57, 313, '个人知识管理系统 · 需求梳理', 28, 'serif ink', 650),
        text(x + 57, 365, '今天 09:42', 12, 'ui muted'),
        rect(x + 1096, 315, 52, 52, '#FFFAF6', 12, '#E6CFC1'),
        icon('arrow', x + 1111, 330, '#965540'),
        text(x, 471, '最近笔记', 24, 'serif ink', 650),
        text(x + 1180, 468, '查看全部  →', 12, 'ui muted', None, None, 'end'),
    ]
    for i, (title, date) in enumerate([
        ('第二大脑的几点思考', '今天'),
        ('信息检索课程', '昨天'),
        ('毕业设计 · 接口与数据结构', '9 月 30 日'),
    ]):
        note_card(parts, x + i * 400, 501, title, date)
    return '\n'.join(parts + ['</svg>'])


def notebook_view(collapsed=False):
    parts = begin('笔记本页面：' + ('列表收起' if collapsed else '列表展开'))
    rail(parts, 'book')
    if not collapsed:
        pane(parts, 'notebooks')
    x = 247 if collapsed else 365
    toolbar(parts, x, '课程学习', with_toggle=True)
    for i, (title, date) in enumerate([
        ('信息检索课程', '昨天'),
        ('阅读方法整理', '9 月 29 日'),
        ('研究计划', '9 月 26 日'),
        ('数据库基础', '9 月 22 日'),
        ('课堂随记', '9 月 18 日'),
        ('阶段总结', '9 月 14 日'),
    ]):
        note_card(parts, x + (i % 3) * 400, 230 + (i // 3) * 334, title, date, selected=i == 0)
    return '\n'.join(parts + ['</svg>'])


def ai_view(collapsed=False):
    parts = begin('AI 对话页面：' + ('列表收起' if collapsed else '列表展开'))
    rail(parts, 'spark')
    if not collapsed:
        pane(parts, 'ai')
    d = -121 if collapsed else 0
    parts += [
        icon('panel', 365 + d, 105, '#9A8376'),
        text(413 + d, 143, '笔记助手', 39, 'serif ink', 650),
        f'<line x1="{365+d}" y1="176" x2="{1545+d}" y2="176" stroke="#E9DFD8"/>',
        rect(1036 + d, 234, 480, 72, '#F0E2D9', 15),
        text(1064 + d, 277, '如何整理检索笔记？', 17, 'ui ink', 550),
        rect(402 + d, 356, 764, 190, '#FFFEFC', 16, '#E9DFD7'),
        rect(402 + d, 356, 4, 190, '#BB7965', 2),
        text(432 + d, 400, '按主题归档，再补充原文来源。', 18, 'serif ink', 600),
        rect(432 + d, 443, 164, 34, '#F5E9E1', 8),
        text(514 + d, 466, '信息检索课程', 12, 'ui', 600, '#86513F', 'middle'),
        rect(606 + d, 443, 124, 34, '#F5E9E1', 8),
        text(668 + d, 466, '需求梳理', 12, 'ui', 600, '#86513F', 'middle'),
        rect(402 + d, 835, 1114, 66, '#FFFFFF', 13, '#E8DDD4'),
        text(426 + d, 875, '向笔记提问', 15, 'ui muted'),
        rect(1450 + d, 847, 52, 42, '#965540', 10),
        icon('send', 1465 + d, 857, '#FFFFFF', 21),
    ]
    return '\n'.join(parts + ['</svg>'])


if __name__ == '__main__':
    for filename, content in [
        ('maple-notes-home.svg', notes_home()),
        ('maple-notebook-list.svg', notebook_view(False)),
        ('maple-notebook-collapsed.svg', notebook_view(True)),
        ('maple-ai-conversations.svg', ai_view()),
        ('maple-ai-collapsed.svg', ai_view(True)),
    ]:
        (OUT / filename).write_text(content, encoding='utf-8')
