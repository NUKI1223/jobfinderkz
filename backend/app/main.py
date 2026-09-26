from fastapi import FastAPI, Depends, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from .config import settings
from .db import Record
from .security import current_user, db_session
from .store import owned
from .revisions import match_current

from .http_common import public_record, upload, attempts
from .routes import accounts as accounts_routes
from .routes import resumes as resumes_routes
from .routes import vacancies as vacancies_routes
from .routes import documents as documents_routes
from .routes import interviews as interviews_routes
from .routes import jobs as jobs_routes
from .routes import knowledge as knowledge_routes
from .routes import usage as usage_routes

app = FastAPI(title='JobFinderKZ', version='0.1.0', docs_url='/api/docs')
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_origin], allow_credentials=True,
                   allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Content-Type', 'X-CSRF-Token', 'Idempotency-Key', 'If-Match'])
PREFIX = '/api/v1'


@app.middleware('http')
async def security_headers(request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != settings.app_origin:
        return Response('Недопустимый Origin', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def invalid_value(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={'detail': str(exc)})


@app.get(PREFIX + '/health')
def health(db=Depends(db_session)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}


@app.get(PREFIX + '/records/{kind}')
def records(kind: str, user=Depends(current_user), db=Depends(db_session)):
    if kind not in ('cv', 'vacancy', 'document', 'plan', 'interview'):
        raise HTTPException(404)
    rows = db.scalars(select(Record).where(Record.kind == kind, Record.owner_id == user.id).order_by(Record.created_at.desc())).all()
    result = []
    for row in rows:
        value = public_record(row)
        if row.kind == 'vacancy' and row.data.get('match'):
            cv = db.get(Record, row.data['match'].get('cv_id', ''))
            value['data']['match_stale'] = not cv or cv.owner_id != user.id or not match_current(row.data['match'], cv, row)
        result.append(value)
    return result


@app.get(PREFIX + '/record/{record_id}')
def record(record_id: str, user=Depends(current_user), db=Depends(db_session)):
    return public_record(owned(db, record_id, user.id))



app.include_router(accounts_routes.router)
app.include_router(resumes_routes.router)
app.include_router(vacancies_routes.router)
app.include_router(documents_routes.router)
app.include_router(interviews_routes.router)
app.include_router(jobs_routes.router)
app.include_router(knowledge_routes.router)
app.include_router(usage_routes.router)

from .routes import study
app.include_router(study.router)
