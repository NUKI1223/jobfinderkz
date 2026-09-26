import shutil
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select, text, delete
from sqlalchemy.exc import IntegrityError
from argon2.exceptions import VerificationError
from ..config import settings
from ..db import User, Login
from ..security import current_user, db_session, passwords, digest, new_session, user_dict
from ..schemas import Credentials, Profile

from fastapi import APIRouter
from ..http_common import PREFIX, throttle

router = APIRouter()

@router.post(PREFIX + '/auth/register')
def register(body: Credentials, request: Request, response: Response, db=Depends(db_session)):
    throttle(request)
    user = User(email=body.email, password_hash=passwords.hash(body.password), profile=Profile().model_dump(),
                role='admin' if body.email == settings.admin_email.lower() else 'user')
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Этот email уже зарегистрирован')
    return new_session(db, user, response)


@router.post(PREFIX + '/auth/login')
def login(body: Credentials, request: Request, response: Response, db=Depends(db_session)):
    throttle(request)
    user = db.scalar(select(User).where(User.email == body.email))
    try:
        if not user or not passwords.verify(user.password_hash, body.password):
            raise HTTPException(401, 'Неверный email или пароль')
    except VerificationError:
        raise HTTPException(401, 'Неверный email или пароль')
    return new_session(db, user, response)


@router.get(PREFIX + '/auth/me')
def me(request: Request, user=Depends(current_user)):
    return {'user': user_dict(user), 'csrf': request.state.csrf}


@router.post(PREFIX + '/auth/logout')
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(db_session)):
    db.execute(delete(Login).where(Login.token == digest(request.cookies.get('jf_session', ''))))
    db.commit()
    response.delete_cookie('jf_session', path='/')
    return {'ok': True}


@router.put(PREFIX + '/profile')
def profile(body: Profile, user=Depends(current_user), db=Depends(db_session)):
    user.profile = body.model_dump()
    db.commit()
    return user_dict(user)


@router.delete(PREFIX + '/account')
def delete_account(response: Response, user=Depends(current_user), db=Depends(db_session)):
    # Same key as worker: deletion cannot race a job that would recreate files.
    if not db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtext(:key))'), {'key': 'user:' + user.id}):
        raise HTTPException(409, 'Дождитесь завершения текущего задания и повторите удаление')
    folder = (settings.storage_path / 'users' / user.id).resolve()
    root = (settings.storage_path / 'users').resolve()
    if folder.parent != root:
        raise HTTPException(500, 'Некорректный путь хранилища')
    shutil.rmtree(folder, ignore_errors=True)
    db.delete(user)
    db.commit()
    response.delete_cookie('jf_session', path='/')
    return {'ok': True}
