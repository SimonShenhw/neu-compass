"""POST /feedback — a completed-answer receipt authorizes one latest vote."""

import sqlite3

from fastapi import APIRouter, HTTPException, Response

from api.dependencies import DbConn
from config import settings
from db.answer_feedback_repository import AnswerFeedbackRepository
from schemas.answer_feedback import AnswerFeedbackRequest, AnswerFeedbackResponse

router = APIRouter(prefix='/feedback', tags=['feedback'])


@router.post('', response_model=AnswerFeedbackResponse,
    responses={404: {'description':'Receipt invalid, expired or unavailable'},
               503: {'description':'Feedback schema/storage unavailable'}})
def submit_feedback(req: AnswerFeedbackRequest, conn: DbConn, response: Response):
    if settings.answer_feedback_enabled is not True:
        raise HTTPException(503, 'Answer feedback is disabled', headers={'Cache-Control': 'no-store'})
    repo = AnswerFeedbackRepository(conn)
    try:
        if not repo.schema_available():
            raise HTTPException(503, 'Feedback unavailable; apply the explicit v1.7 migration')
        repo.vote(req)
        conn.commit()
    except LookupError as exc:
        raise HTTPException(404, 'Feedback target unavailable') from exc
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(503, 'Feedback storage temporarily unavailable') from exc
    response.headers['Cache-Control'] = 'no-store'
    return AnswerFeedbackResponse(answer_id=req.answer_id, rating=req.rating)
