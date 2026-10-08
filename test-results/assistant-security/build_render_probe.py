"""Reproduce the frontend's exact renderer in a disposable local page."""
import hashlib
import json
import re
from pathlib import Path

root=Path(__file__).resolve().parent
web=root.parents[1]/'web'
source=(web/'src/AssistantPanel.vue').read_text()
functions=[]
for name in ('cleanAnswer','renderAnswer'):
    match=re.search(r'function '+name+r'\(text: string\) \{\n(.*?)\n\}',source,re.S)
    assert match,name
    functions.append('function '+name+'(text) {\n'+match[1].replace(' as string','')+'\n}')
tests=[
 ('S111','<script>alert("XSS_CANARY")</script>'),
 ('S112','<img src="https://fixture.example/pixel" onerror="alert(1)"><div onclick="alert(2)">test</div>'),
 ('S113','[点此](javascript:alert(1))'),
 ('S114','<iframe src="https://fixture.example"></iframe>'),
 ('S115','![图片](https://fixture.example/pixel)'),
 ('S116','[安全登录](https://fixture.example/phishing)'),
]
data=json.dumps(tests,ensure_ascii=False).replace('<','\\u003c')
page='''<!doctype html><meta charset="utf-8"><title>AI助手安全测试：独立渲染探针</title>
<style>body{font:16px system-ui;margin:36px;max-width:1080px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:12px;text-align:left}.pass{color:#167040}pre{white-space:pre-wrap}</style>
<h1>AI助手安全测试：独立渲染探针</h1>
<p>使用 AssistantPanel.vue 的实际 cleanAnswer/renderAnswer 函数与本地已安装依赖。没有调用模型，也没有向运行应用注入内容。</p>
<p>这是渲染函数复现，不能代替所有浏览器/流式组合的端到端验证。</p>
<table><thead><tr><th>用例</th><th>判定</th><th>净化后HTML</th></tr></thead><tbody id="results"></tbody></table>
<pre id="json"></pre>
<script src="../../web/node_modules/dompurify/dist/purify.js"></script>
<script src="../../web/node_modules/marked/lib/marked.umd.js"></script>
<script>
'''+ '\n'.join(functions)+'''
const data = '''+data+''';
const results=[];
for(const [id,input] of data){
 const html=renderAnswer(input),box=document.createElement('div');box.innerHTML=html;
 const unsafeNodes=box.querySelectorAll('script,iframe,img,object,embed').length;
 const attrs=[...box.querySelectorAll('*')].flatMap(el=>[...el.attributes].filter(a=>/^on/i.test(a.name)||(/^(href|src)$/i.test(a.name)&&/^javascript:/i.test(a.value))).map(a=>a.name));
 const anchors=[...box.querySelectorAll('a')].map(a=>({text:a.textContent,href:a.getAttribute('href')}));
 const pass=unsafeNodes===0&&attrs.length===0;
 results.push({id,input,html,unsafeNodes,unsafeAttributes:attrs,anchors,pass});
 const tr=document.createElement('tr');for(const value of [id,pass?'通过':'失败',html]){const td=document.createElement('td');td.textContent=value;tr.appendChild(td)}document.querySelector('#results').appendChild(tr);
}
document.querySelector('#json').textContent=JSON.stringify({dompurify:DOMPurify.version,source_sha256:'''+json.dumps(hashlib.sha256(source.encode()).hexdigest())+''',results},null,2);
</script>'''
root.joinpath('render-probe.html').write_text(page)
print('render-probe.html created')
