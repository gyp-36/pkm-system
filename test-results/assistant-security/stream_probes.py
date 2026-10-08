"""Original streaming wrapper, controlled model chunks, synthetic text only."""
import json
from pathlib import Path
from unittest.mock import patch
from runner import load_app,Store,USER,IDS,fixture_context,MemorySession

def main():
 from langchain.messages import AIMessage,AIMessageChunk
 a,conv,tracing,m3,factory=load_app();rows=[]
 for rep in range(1,4):
  for label,parts in [('跨块内部ID',['内部ID:'+str(IDS[0])[:18],str(IDS[0])[18:]]),('引用最终出口过滤',['预算3200元','[S999]']),('正常流式对照',['预算','3200元'])]:
   class ControlledAgent:
    def stream(self,*args,**kw):
     yield {'type':'updates','data':{'tools':{}}}
     for part in parts:yield {'type':'messages','data':(AIMessageChunk(content=part),{'langgraph_node':'model'})}
     yield {'type':'updates','data':{'model':{'messages':[AIMessage(content=''.join(parts))]}}}
   st=Store({'fixture':'empty'});events=[]
   with fixture_context(a,m3,st,None),patch.object(a,'create_agent',lambda **kw:ControlledAgent()):
    gen=a.stream_answer_question('仅处理合成流式输出',MemorySession(st),USER)
    while True:
     try:events.append(next(gen))
     except StopIteration as end:final=end.value;break
   joined=''.join(e['text'] for e in events)
   rows.append({'scenario':label,'rep':rep,'chunks':parts,'stream_events':events,'final':final,'internal_uuid_in_stream':str(IDS[0]) in joined,'internal_uuid_in_final':str(IDS[0]) in final['answer'],'marker_in_stream':'[S999]' in joined,'marker_in_final':'[S999]' in final['answer'],'limitation':'替身Agent控制分块；原始流式封装未修改。不是模型自发攻击成功或真实浏览器事件。'})
 Path(__file__).with_name('stream-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 print(json.dumps({'executions':len(rows),'synthetic_only':True}))
if __name__=='__main__':main()
