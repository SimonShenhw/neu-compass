"""Bind a receipt to the exact displayed answer; submit only explicit clicks."""

import hashlib

from app.api_client import ApiClient, ApiError
from config import settings
from schemas.answer_feedback import AnswerFeedbackReceipt, AnswerFeedbackResponse

CAPTURE_OPT_IN_KEY = 'answer_feedback_capture_opt_in'
QUERY_LOG_NOTICE = '提问原文仍会写入私有查询日志；关闭回答反馈不关闭该日志。请勿输入个人信息或秘密。'
CAPTURE_NOTICE = (
    '若服务可用，勾选后本会话后续正常完成的回答及筛选上下文会私有保存，'
    '即使不点击 👍／👎 也会保存。历史只新增轮数，不新增完整历史文本。'
    '7 天仅是投票凭证有效期，数据／备份／导出不会自动删除；'
    '取消勾选、清空对话或登出不会删除已保存的数据。'
)


def render_feedback_capture_control(st):
    """Notice before input; local permission never overrides the API kill switch."""
    st.caption(QUERY_LOG_NOTICE)
    if settings.answer_feedback_enabled is not True:
        st.session_state.pop(CAPTURE_OPT_IN_KEY, None)
        st.caption('完整回答反馈保存当前关闭；聊天与原查询日志仍按原机制运行。')
        return False
    if CAPTURE_OPT_IN_KEY in st.session_state and type(st.session_state[CAPTURE_OPT_IN_KEY]) is not bool:
        st.session_state.pop(CAPTURE_OPT_IN_KEY, None)
    st.caption(CAPTURE_NOTICE)
    return st.checkbox('允许本次会话后续回答保存，用于回答反馈', value=False,
        key=CAPTURE_OPT_IN_KEY, help='默认不勾选；取消只停止后续回答保存，不撤销已有保存或投票。') is True


def bind_feedback_receipt(receipt, content):
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        target = AnswerFeedbackReceipt.model_validate(receipt)
    except ValueError:
        return None
    if hashlib.sha256(content.encode('utf-8')).hexdigest() != target.answer_sha256:
        return None
    return target.model_dump(mode='json')


def render_answer_feedback(st, message, *, key_prefix):
    if settings.answer_feedback_enabled is not True:
        return
    if message.get('role') != 'assistant':
        return
    target = bind_feedback_receipt(message.get('feedback'), message.get('content'))
    if target is None:
        return
    st.caption('只评价这条回答；不是选课或毕业资格确认。反馈关联此回答及原查询，不收额外文本。')
    selected = message.get('feedback_rating')
    if not isinstance(selected, str) or selected not in {'up','down'}:
        selected = None
    columns = st.columns(2)
    rating = None
    for column, value, label in zip(columns, ['up','down'], ['👍 有帮助','👎 没帮助']):
        if column.button(label, key=f'{key_prefix}-{target["answer_id"]}-{value}', disabled=selected == value):
            rating = value
    if rating is None:
        if selected in {'up','down'}:
            st.caption('已记录评价，可点击另一项修改。')
        return
    try:
        with ApiClient(session_token=st.session_state.get('session_token'), timeout=8.0) as api:
            response = AnswerFeedbackResponse.model_validate(api.submit_answer_feedback({**target,'rating':rating}))
        if response.answer_id != target['answer_id'] or response.rating != rating:
            raise ValueError('Feedback response does not match this click')
    except ApiError as exc:
        if exc.status_code == 404:
            st.warning('反馈凭证已过期或不可用；未保存本次评价。')
        else:
            st.warning('反馈暂时无法保存；未标记为成功，可稍后重试。')
        return
    except ValueError:
        st.warning('反馈响应校验失败；未标记为成功。')
        return
    message['feedback_rating'] = rating
    st.success('反馈已保存，仅记录此回答的一条最新评价。')
