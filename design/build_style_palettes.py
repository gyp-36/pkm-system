from pathlib import Path


PALETTES = [
    ('01', '枫叶纸感', '推荐', ['#FCFAF7', '#F4EEE8', '#FFFEFC', '#3C322E', '#6F625B', '#965540']),
    ('02', '中性编辑器', '', ['#FAFAF8', '#F0F0EC', '#FFFFFF', '#292B29', '#626862', '#576F62']),
    ('03', '雾蓝书房', '', ['#F7FAFA', '#EAF1F2', '#FFFFFF', '#26363D', '#5F7076', '#4D7180']),
]
ROLES = ['背景', '侧栏', '卡片', '主文字', '辅助字', '强调色']


def build():
    p = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1420" height="744" viewBox="0 0 1420 744" role="img" aria-labelledby="title desc">',
        '<title id="title">笔记系统风格与配色比较</title>',
        '<desc id="desc">三套不改变布局的配色提案：枫叶纸感、中性编辑器、雾蓝书房。</desc>',
        '<rect width="1420" height="744" fill="#EDEAE6"/>',
    ]
    for i, (number, name, badge, colors) in enumerate(PALETTES):
        y = 28 + i * 238
        p.append(f'<rect x="26" y="{y}" width="1368" height="214" rx="17" fill="{colors[0]}" stroke="#DDD8D2"/>')
        p.append(f'<text x="57" y="{y+60}" fill="{colors[3]}" font-family="Songti SC,STSong,serif" font-size="28" font-weight="650">{number}  {name}</text>')
        if badge:
            p.append(f'<rect x="257" y="{y+32}" width="53" height="27" rx="7" fill="#EBD9CF"/>')
            p.append(f'<text x="283.5" y="{y+51}" fill="#744634" font-family="PingFang SC,Hiragino Sans GB,sans-serif" font-size="12" font-weight="650" text-anchor="middle">{badge}</text>')
        for j, (role, color) in enumerate(zip(ROLES, colors)):
            sx = 355 + j * 165
            p.append(f'<rect x="{sx}" y="{y+29}" width="134" height="104" rx="10" fill="{color}" stroke="#CEC9C3"/>')
            p.append(f'<text x="{sx}" y="{y+159}" fill="{colors[3]}" font-family="PingFang SC,Hiragino Sans GB,sans-serif" font-size="12">{role}</text>')
            p.append(f'<text x="{sx}" y="{y+181}" fill="{colors[4]}" font-family="ui-monospace,monospace" font-size="11">{color}</text>')
    p.append('</svg>')
    return '\n'.join(p)


if __name__ == '__main__':
    Path(__file__).with_name('style-palette-comparison.svg').write_text(build(), encoding='utf-8')
