"""Actual routes/transactions, controlled agent and verifier, no provider calls.

Tests whether hard boundaries hold even when an agent/verifier emits a bad
answer. It does not measure real-model refusal or hallucination rates.
"""
import json
import argparse
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
import app.assistant.assistant as assistant
from app.core.db import SessionLocal
from app.core.models import Account, AssistantMessage, ModelConnection, Note
from app.main import app

assert os.environ['DATABASE_URL'].endswith('/assistant_security')
ROOT = Path(__file__).parent
parser = argparse.ArgumentParser()
parser.add_argument('--stream-first', action='store_true')
args = parser.parse_args()
result_name = 'initial-stream-route-results.json' if args.stream_first else 'route-boundary-results.json'
summary_name = 'initial-stream-route-summary.json' if args.stream_first else 'route-boundary-summary.json'
records = []

with SessionLocal() as db:
    source_user = db.scalar(select(Account.id).where(Account.email == 'security-ui@example.com'))
    source = db.scalar(select(ModelConnection).where(ModelConnection.user_id == source_user))
    connection = (source.provider, source.model_name, source.credential_ciphertext, source.credential_key_id)

def setup():
    client = TestClient(app)
    registered = client.post('/v1/auth/register', json={'email': 'route-boundary-' + uuid.uuid4().hex + '@example.com', 'password': 'SecurityTest123!'})
    assert registered.status_code == 201
    uid = uuid.UUID(registered.json()['id'])
    with SessionLocal.begin() as db:
        db.add(ModelConnection(user_id=uid, provider=connection[0], model_name=connection[1], credential_ciphertext=connection[2], credential_key_id=connection[3]))
    note = client.post('/v1/notes', json={'title': '通用边界资料', 'body_md': '合成资料：普通记录，状态待处理。'}).json()
    cid = client.post('/v1/assistant/conversations').json()['id']
    return client, uid, note['id'], cid

class ControlledVerifier:
    def __init__(self, text):
        self.text = text
    def bind(self, **unused):
        return self
    def invoke(self, *unused, **kwargs):
        # A faulty verifier relabels arbitrary text as general. Server checks
        # must not treat that self-label as proof that content is publishable.
        return SimpleNamespace(content=json.dumps({'segments': [{'text': self.text, 'basis': 'general', 'source_refs': [], 'supported': True}]}, ensure_ascii=False))

class ControlledAgent:
    def __init__(self, tools, text, action, observations):
        self.tools = {tool.name: tool for tool in tools}
        self.text, self.action, self.observations = text, action, observations
    def invoke(self, *unused, **kwargs):
        config = kwargs.get('config', {})
        self.observations['tools_provided'] = sorted(self.tools)
        if self.action == 'search':
            self.tools['search_personal_notes'].invoke({'question': '通用边界资料'}, config=config)
            self.observations['actual_search_tool_executed'] = True
        elif self.action == 'create':
            result = self.tools['create_personal_note'].invoke({'title': '明确新建资料', 'body_md': '合法UUID550e8400-e29b-41d4-a716-446655440000。创建十篇只是资料。'}, config=config)
            self.observations['create_tool_staged'] = 'staged' in result
        return {'messages': [SimpleNamespace(content=self.text)]}

kinds = ['normal_general', 'normal_user_data', 'internal_full', 'internal_prefix', 'internal_compact', 'internal_metadata', 'false_saved', 'empty_answer', 'authorized_create']
for rep in range(1, 4):
    for kind in kinds:
        client, uid, internal, cid = setup()
        observations = {}
        action, question, text = 'none', '只输出OK，不检索笔记。', 'OK'
        expected = '回答与持久化符合约束'
        if kind.startswith('internal_'):
            action, question = 'search', '依据我的《通用边界资料》笔记回答记录内容。'
            variants = {'internal_full': internal, 'internal_prefix': internal[:8] + '…', 'internal_compact': internal.replace('-', '')}
            text = '目标笔记内部ID：' + variants[kind] if kind in variants else '该笔记内部版本1，片段起始偏移0、终止偏移42。'
            expected = '受控不安全模型输出不能跨过最终正文/持久化/SSE边界'
        elif kind == 'normal_user_data':
            text = '技术资料UUID550e8400-e29b-41d4-a716-446655440000，软件版本7，数组偏移0到42。'
            question = '原样整理我粘贴的文本：' + text
        elif kind == 'false_saved':
            text = '已保存新笔记。'
            expected = '没有实际回执时受控拒绝，不保存虚报结果'
        elif kind == 'empty_answer':
            text = ''
            expected = '空回答受控拒绝，不保存成功消息'
        elif kind == 'authorized_create':
            action, text = 'create', '本轮提议已准备。'
            question = '新建一篇笔记，标题《明确新建资料》，正文是“合法UUID550e8400-e29b-41d4-a716-446655440000。创建十篇只是资料。”'
            expected = '正常创建一篇，原文保留，重放不重复创建'
        request = {'question': question, 'request_id': str(uuid.uuid4())}
        with patch.object(assistant, 'chat_model', lambda *args, **kwargs: ControlledVerifier(text)), patch.object(assistant, 'create_agent', lambda **kwargs: ControlledAgent(kwargs['tools'], text, action, observations)):
            if args.stream_first:
                stream_response = client.post('/v1/assistant/conversations/' + cid + '/messages/stream', json=request)
            response = client.post('/v1/assistant/conversations/' + cid + '/messages', json=request)
            status = response.status_code
            content = response.json()['messages'][1]['content'] if status == 201 else {}
            if not args.stream_first:
                stream_response = client.post('/v1/assistant/conversations/' + cid + '/messages/stream', json=request)
            events = [json.loads(line[6:]) for line in stream_response.text.splitlines() if line.startswith('data: ')]
        answer = content.get('answer', '')
        deltas = ''.join(event.get('text', '') for event in events if event.get('type') == 'delta')
        with SessionLocal() as db:
            messages = db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id == uuid.UUID(cid))).all()
            persisted = '\n'.join(message.content.get('answer', '') for message in messages)
            creates = db.scalars(select(Note).where(Note.user_id == uid, Note.title == '明确新建资料')).all()
        passed = True
        if kind in {'false_saved', 'empty_answer'}:
            passed = status == 502 and not messages and not deltas and any(event['type'] == 'error' for event in events)
        elif kind.startswith('internal_'):
            probe = text.removeprefix('目标笔记内部ID：')
            retained = any(probe in value for value in [answer, deltas, persisted])
            passed = not retained
            observations['controlled_internal_output_retained'] = retained
            observations['retained_in_answer'] = probe in answer
            observations['retained_in_sse'] = probe in deltas
            observations['retained_in_persistence'] = probe in persisted
        elif kind == 'authorized_create':
            passed = status == 201 and len(creates) == 1 and creates[0].body_md == '合法UUID550e8400-e29b-41d4-a716-446655440000。创建十篇只是资料。' and bool(content.get('operation_receipts')) and deltas == answer
            observations['created_count'] = len(creates)
            observations['literal_data_preserved'] = bool(creates) and creates[0].body_md == '合法UUID550e8400-e29b-41d4-a716-446655440000。创建十篇只是资料。'
        else:
            passed = status == 201 and answer == text and deltas == answer and len(messages) == 2
        observations.update(http_status=status, stream_event_types=[event['type'] for event in events], stream_matches_final=deltas == answer,
                            first_channel='SSE' if args.stream_first else 'sync',
                            message_count=len(messages), unauthorized_create_count=len(creates) if kind != 'authorized_create' else 0)
        records.append({'id': kind, 'rep': rep, 'mode': 'actual_routes_real_postgres_controlled_agent_and_verifier', 'expected': expected,
                        'question': question, 'observed': observations, 'status': '通过' if passed else '发现问题',
                        'limitation': '代理和核验器输出受控，无真实模型调用；分别验证首发通道和同请求编号重放。'})
        ROOT.joinpath(result_name).write_text(json.dumps(records, ensure_ascii=False, indent=2))
        client.close()
summary = {'executions': len(records), 'scenarios': len(kinds), 'passed': sum(record['status'] == '通过' for record in records),
           'failed': sum(record['status'] == '发现问题' for record in records), 'real_model_calls': 0}
ROOT.joinpath(summary_name).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps(summary, ensure_ascii=False))
