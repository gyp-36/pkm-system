// No browser control, no script execution, no network: an in-memory DOM probe.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';

const root=path.dirname(fileURLToPath(import.meta.url));
const web=path.resolve(root,'../../web');
const require=createRequire(import.meta.url);
const { JSDOM }=require(path.join(root,'.renderer-runtime/node_modules/jsdom'));
const createDOMPurify=require(path.join(web,'node_modules/dompurify/dist/purify.cjs.js'));
const { marked }=await import(path.join(web,'node_modules/marked/lib/marked.esm.js'));
const source=fs.readFileSync(path.join(web,'src/AssistantPanel.vue'),'utf8');
const defs=['cleanAnswer','renderAnswer'].map(name=>{
 const pattern=new RegExp('function '+name+'\\(text: string\\) \\{\\n([\\s\\S]*?)\\n\\}');
 const match=source.match(pattern);if(!match)throw new Error('Missing renderer '+name);
 return 'function '+name+'(text){\n'+match[1].replaceAll(' as string','')+'\n}';
}).join('\n');
const window=new JSDOM('').window; // default: neither scripts nor resources execute
const DOMPurify=createDOMPurify(window);
const context=vm.createContext({DOMPurify,marked});
new vm.Script(defs).runInContext(context);
const tests=[
 ['S111','<script>alert("XSS_CANARY")</script>'],
 ['S112','<img src="https://fixture.example/pixel" onerror="alert(1)"><div onclick="alert(2)">test</div>'],
 ['S113','[点此](javascript:alert(1))'],
 ['S114','<iframe src="https://fixture.example"></iframe>'],
 ['S115','![图片](https://fixture.example/pixel)'],
 ['S116','[安全登录](https://fixture.example/phishing)'],
];
const results=tests.map(([id,input])=>{
 const html=context.renderAnswer(input),box=window.document.createElement('div');box.innerHTML=html;
 const unsafeNodes=box.querySelectorAll('script,iframe,img,object,embed').length;
 const unsafeAttributes=[...box.querySelectorAll('*')].flatMap(el=>[...el.attributes]
  .filter(a=>/^on/i.test(a.name)||(/^(href|src)$/i.test(a.name)&&/^javascript:/i.test(a.value))).map(a=>a.name));
 return {id,input,html,unsafeNodes,unsafeAttributes,pass:unsafeNodes===0&&unsafeAttributes.length===0,
  anchors:[...box.querySelectorAll('a')].map(a=>({text:a.textContent,href:a.getAttribute('href')}))};
});
const output={mode:'actual_renderer_in_memory_dom',network:false,scripts_executed:false,
 source_sha256:crypto.createHash('sha256').update(source).digest('hex'),
 dompurify:DOMPurify.version,marked:JSON.parse(fs.readFileSync(path.join(web,'node_modules/marked/package.json'))).version,
 jsdom:JSON.parse(fs.readFileSync(path.join(root,'.renderer-runtime/node_modules/jsdom/package.json'))).version,
 results,limitation:'渲染函数和依赖与运行Web容器指纹一致；DOM探针不等同全浏览器事件、CSS或网络行为验证。S116允许普通外链，未宣称能识别钓鱼。'};
fs.writeFileSync(path.join(root,'render-results.json'),JSON.stringify(output,null,2));
window.close();
console.log(JSON.stringify({tests:results.length,passed:results.filter(r=>r.pass).length}));
