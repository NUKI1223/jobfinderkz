import hashlib
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .db import Session, Login, User, now
from .config import settings

passwords = PasswordHasher()


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def db_session():
    with Session() as db:
        yield db


def current_user(request: Request, db=Depends(db_session)):
    token = request.cookies.get('jf_session', '')
    login = db.get(Login, digest(token)) if token else None
    if not login or login.expires < now():
        raise HTTPException(401, 'Войдите в аккаунт')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if not secrets.compare_digest(request.headers.get('x-csrf-token', ''), login.csrf):
            raise HTTPException(403, 'Обновите страницу: проверка CSRF не пройдена')
    user = db.get(User, login.user_id)
    if not user:
        raise HTTPException(401, 'Аккаунт удалён')
    request.state.csrf = login.csrf
    return user


def admin(user=Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Требуется роль администратора')
    return user


def new_session(db, user, response):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(Login(token=digest(token), user_id=user.id, csrf=csrf, expires=now() + timedelta(days=7)))
    db.commit()
    response.set_cookie('jf_session', token, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=604800, path='/')
    return {'user': user_dict(user), 'csrf': csrf}


def user_dict(user):
    return {'id': user.id, 'email': user.email, 'role': user.role, 'profile': user.profile}
