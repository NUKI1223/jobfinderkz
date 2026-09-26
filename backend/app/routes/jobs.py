from fastapi import Depends, HTTPException
from sqlalchemy import select, or_
from ..db import Job
from ..security import current_user, db_session

from fastapi import APIRouter
from ..http_common import PREFIX, job_dict

router = APIRouter()

@router.get(PREFIX + '/jobs')
def job_list(user=Depends(current_user), db=Depends(db_session)):
    return [job_dict(j) for j in db.scalars(select(Job).where(or_(Job.owner_id == user.id, Job.kind == 'index_knowledge' if user.role == 'admin' else False)).order_by(Job.created_at.desc()).limit(100))]


@router.get(PREFIX + '/jobs/{job_id}')
def get_job(job_id: str, user=Depends(current_user), db=Depends(db_session)):
    job = db.get(Job, job_id)
    if not job or (job.owner_id != user.id and not (user.role == 'admin' and job.kind == 'index_knowledge')):
        raise HTTPException(404)
    return job_dict(job)


@router.post(PREFIX + '/jobs/{job_id}/resume')
def resume_job(job_id: str, user=Depends(current_user), db=Depends(db_session)):
    job = db.get(Job, job_id)
    if not job or (job.owner_id != user.id and not (user.role == 'admin' and job.kind == 'index_knowledge')):
        raise HTTPException(404)
    if job.status not in ('paused', 'failed') or job.attempts >= 3:
        raise HTTPException(409, 'Нельзя повторить: требуется проверка, достигнут лимит попыток или задание уже выполняется')
    job.status, job.error = 'queued', None
    db.commit()
    return job_dict(job)
