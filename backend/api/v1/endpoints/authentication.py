from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.config import settings
from ....core.database import get_db
from ....core.rate_limit import limited_login, limited_registration, limited_email_send, RATE_LIMIT_RESPONSES
from ....core.security import (
    create_access_token,
    get_current_user,
    issue_web_session,
    request_token,
    revoke_access_token,
    touch_web_session,
    WEB_SESSION_COOKIE,
    WEB_SESSION_MAX_SECONDS,
)
from ....crud.user import crud_user
from ....database.models.user import User
from ....database.sсhemas.user import Token, UserCreate, UserLogin, UserMe, UserOut, EmailCode
from backend.services.email_verification import issue_code, confirm_code, code_status, CODE_SECONDS
from fastapi import BackgroundTasks
from backend.core.rate_limit import limited_reset_request, limited_reset_attempt
from backend.database.sсhemas.password_reset import ResetRequest, ResetCode, ResetFinish
from backend.services import password_reset


router = APIRouter(tags=["authentication"])


@router.post("/password/request", dependencies=[Depends(limited_reset_request)], responses=RATE_LIMIT_RESPONSES)
async def request_password_reset(data: ResetRequest, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    user = await crud_user.get_by_email(db, data.email)
    await password_reset.request_reset(db, user, background)
    return {"detail": password_reset.REQUEST_MESSAGE, "expires_in_seconds": 120, "resend_after_seconds": 120}


@router.post("/password/verify", dependencies=[Depends(limited_reset_attempt)], responses=RATE_LIMIT_RESPONSES)
async def verify_password_code(data: ResetCode, db: AsyncSession = Depends(get_db)):
    return await password_reset.verify_code(db, await crud_user.get_by_email(db, data.email), data.code)


@router.post("/password/reset", dependencies=[Depends(limited_reset_attempt)], responses=RATE_LIMIT_RESPONSES)
async def reset_password(data: ResetFinish, response: Response, db: AsyncSession = Depends(get_db)):
    result = await password_reset.finish_reset(db, data.reset_token, data.new_password)
    response.delete_cookie(WEB_SESSION_COOKIE, path="/api/v1")
    return result


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED, responses=RATE_LIMIT_RESPONSES,
             dependencies=[Depends(limited_registration)])
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    if await crud_user.get_by_email(db, user_data.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    if await crud_user.get_by_username(db, user_data.username):
        raise HTTPException(status_code=409, detail="Username already taken")

    try:
        user = await crud_user.create_user_with_profile(user_data, db)
        await issue_code(db, user.id)
        await db.commit()
        await db.refresh(user)
        return user
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already registered")


@router.post("/email/resend", responses=RATE_LIMIT_RESPONSES)
async def resend_email(user: User = Depends(limited_email_send), db: AsyncSession = Depends(get_db)):
    await issue_code(db, user.id)
    await db.commit()
    return {"expires_in_seconds": CODE_SECONDS, "resend_after_seconds": CODE_SECONDS}


@router.post("/email/verify", responses=RATE_LIMIT_RESPONSES)
async def verify_email(data: EmailCode, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await confirm_code(db, user.id, data.code)


@router.get("/email/status")
async def email_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await code_status(db, user)


@router.post("/login", response_model=Token, dependencies=[Depends(limited_login)],
             responses={**RATE_LIMIT_RESPONSES, 204: {"description": "Browser session cookie set"}})
async def login(
    form_data: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Token | Response:
    user = await crud_user.authenticate(db, form_data.username, form_data.password)
    if user is None or user.profile is None or not user.profile.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("X-Amergination-Client") == "web":
        access_token = await issue_web_session(user.id, user.auth_version)
        response.set_cookie(WEB_SESSION_COOKIE, access_token, path="/api/v1", httponly=True,
                            secure=request.url.scheme == "https", samesite="strict",
                            max_age=WEB_SESSION_MAX_SECONDS)
        response.status_code = 204
        return response
    access_token = create_access_token(
        user.id, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), token_version=user.auth_version)
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserMe)
async def read_users_me(response: Response, current_user: User = Depends(get_current_user)) -> User:
    response.headers["Cache-Control"] = "no-store"
    return current_user


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_current_user)])
async def keep_session_alive(token: str = Depends(request_token)) -> Response:
    await touch_web_session(token)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token: str = Depends(request_token),
    current_user: User = Depends(get_current_user),
) -> Response:
    await revoke_access_token(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(WEB_SESSION_COOKIE, path="/api/v1")
    return response
