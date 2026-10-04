"""Completed answer + latest receipt-authorized vote. Caller owns commit/close."""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid

from schemas.answer_feedback import (AnswerFeedbackReceipt, AnswerFeedbackRequest,
    FEEDBACK_TTL_SECONDS, MAX_ANSWER_CHARS)

TABLE_COLUMNS = {
    'chat_answers': {'answer_id', 'query_log_id', 'answer_text', 'answer_sha256',
        'feedback_token_hash', 'prompt_version', 'request_context', 'created_at', 'expires_at'},
    'answer_feedback': {'answer_id', 'rating', 'created_at', 'updated_at'},
}
TABLE_FOREIGN_KEYS = {'chat_answers':('query_log','query_log_id','log_id','CASCADE'),
    'answer_feedback':('chat_answers','answer_id','answer_id','CASCADE')}


class AnswerFeedbackRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def schema_available(self) -> bool:
        return all(self.table_available(table) for table in TABLE_COLUMNS)

    def table_available(self, table: str) -> bool:
        if table not in TABLE_COLUMNS:
            return False
        info = list(self.conn.execute(f'PRAGMA table_info({table})'))
        if not TABLE_COLUMNS[table].issubset({r[1] for r in info}):
            return False
        if [(r[1],r[3]) for r in info if r[5]] != [('answer_id',1)]:
            return False
        foreign_keys = {(r[2],r[3],r[4],r[6]) for r in self.conn.execute(f'PRAGMA foreign_key_list({table})')}
        if TABLE_FOREIGN_KEYS[table] not in foreign_keys:
            return False
        if table == 'chat_answers':
            indexes = list(self.conn.execute('PRAGMA index_list(chat_answers)'))
            if not any(r[2] and not r[4] and [c[2] for c in self.conn.execute(
                'SELECT * FROM pragma_index_info(?)', (r[1],))] == ['query_log_id'] for r in indexes):
                return False
        return True

    def store_completed(self, *, query_log_id: int, answer_text: str, prompt_version: str,
                        request_context: dict) -> AnswerFeedbackReceipt:
        if (type(query_log_id) is not int or not isinstance(answer_text, str)
            or not answer_text.strip() or len(answer_text) > MAX_ANSWER_CHARS):
            raise ValueError('No complete bounded answer to persist')
        query = self.conn.execute('SELECT route FROM query_log WHERE log_id=?', (query_log_id,)).fetchone()
        if query is None or query[0] != 'chat':
            raise ValueError('Answer must reference its actual chat query')
        context = json.dumps(request_context, ensure_ascii=False, sort_keys=True)
        if len(context) > 8192 or not isinstance(prompt_version, str) or not 1 <= len(prompt_version) <= 64:
            raise ValueError('Answer metadata outside budget')
        token = secrets.token_urlsafe(32)
        receipt = AnswerFeedbackReceipt(answer_id=uuid.uuid4().hex,
            answer_sha256=hashlib.sha256(answer_text.encode('utf-8')).hexdigest(), feedback_token=token)
        self.conn.execute('INSERT INTO chat_answers '
            '(answer_id,query_log_id,answer_text,answer_sha256,feedback_token_hash,prompt_version,request_context,expires_at) '
            'VALUES (?,?,?,?,?,?,?,?)', (receipt.answer_id, query_log_id, answer_text, receipt.answer_sha256,
            hashlib.sha256(token.encode()).hexdigest(), prompt_version, context, int(time.time()) + FEEDBACK_TTL_SECONDS))
        return receipt

    def vote(self, request: AnswerFeedbackRequest) -> None:
        request = AnswerFeedbackRequest.model_validate(request.model_dump())
        row = self.conn.execute('SELECT answer_text,answer_sha256,feedback_token_hash,expires_at '
            'FROM chat_answers WHERE answer_id=?', (request.answer_id,)).fetchone()
        if (row is None or type(row['expires_at']) is not int
            or any(not isinstance(row[field], str) for field in ['answer_text','answer_sha256','feedback_token_hash'])
            or row['expires_at'] <= int(time.time())
            or row['answer_sha256'] != request.answer_sha256
            or hashlib.sha256(row['answer_text'].encode('utf-8')).hexdigest() != request.answer_sha256
            or not hmac.compare_digest(row['feedback_token_hash'].encode(), hashlib.sha256(request.feedback_token.encode()).hexdigest().encode())):
            raise LookupError('Feedback target unavailable')
        self.conn.execute('INSERT INTO answer_feedback(answer_id,rating) VALUES (?,?) '
            'ON CONFLICT(answer_id) DO UPDATE SET rating=excluded.rating,updated_at=CURRENT_TIMESTAMP '
            'WHERE answer_feedback.rating != excluded.rating', (request.answer_id, request.rating))
