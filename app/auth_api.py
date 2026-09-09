from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.config import settings
from app.db import get_db
from app.ldap_client import authenticate as ldap_authenticate
from app.models import User, utcnow
from app.ratelimit import check as rl_check, clear as rl_clear
from app.verify import issue as issue_verify, read as read_verify
from app.security import COOKIE, hash_password, issue_token, needs_rehash, verify_password

router = APIRouter(prefix="/api/auth")


class LoginIn(BaseModel):
    # deliberately not EmailStr: a validation error here would distinguish
    # a malformed address from an unknown account
    email: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    display_name: str = Field(min_length=1, max_length=120)
    org: str = Field(default="Unspecified", max_length=120)


class Me(BaseModel):
    email: str
    display_name: str
    org: str
    role: str
    auth_source: str


def _set_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        COOKIE,
        issue_token(user.id, user.email, user.effective_role),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )


def _me(u: User) -> Me:
    return Me(
        email=u.email, display_name=u.display_name, org=u.org,
        role=u.effective_role, auth_source=u.auth_source,
    )


@router.post("/register", response_model=Me, status_code=201)
def register(payload: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    exists = db.scalar(select(User).where(func.lower(User.email) == email))
    if exists:
        raise HTTPException(409, "An account with that address already exists")

    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        org=payload.org.strip() or "Unspecified",
        auth_source="local",
        password_hash=hash_password(payload.password),
        role="customer",
        last_login_at=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _send_verification(db, user)
    from app import notify
    notify.on_account_event(db, user, "signup")
    db.commit()
    # no session: the address must be confirmed first
    return _me(user)


@router.post("/login", response_model=Me)
def login(payload: LoginIn, request: Request, response: Response,
          db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    rl_check(request, email)
    user = db.scalar(select(User).where(func.lower(User.email) == email))

    if user is not None and not user.is_active:
        raise HTTPException(401, "Those details did not match an account")

    # local accounts authenticate locally and never touch the directory
    if user is not None and user.auth_source == "local":
        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(401, "Those details did not match an account")
        if not user.email_verified:
            _send_verification(db, user)
            raise HTTPException(
                403,
                "Check your email and confirm your address before signing in. "
                "We have sent another link.",
            )
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(payload.password)
    else:
        ident = ldap_authenticate(email, payload.password)
        if ident is None:
            # same cost and message as a local failure
            hash_password(payload.password)
            raise HTTPException(401, "Those details did not match an account")

        if user is None:
            user = User(email=ident.email, org="Directory", auth_source="ldap")
            db.add(user)
        user.display_name = ident.display_name
        user.ldap_dn = ident.dn
        user.auth_source = "ldap"
        user.password_hash = None
        # role_override still wins in effective_role
        user.role = "agent" if ident.is_agent else "customer"

    user.last_login_at = utcnow()
    db.commit()
    db.refresh(user)

    rl_clear(request, email)
    _set_cookie(response, user)
    return _me(user)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=Me)
def me(user: User = Depends(current_user)):
    return _me(user)


def _send_verification(db: Session, user: User) -> None:
    """Queue a confirmation link. Bypasses the allowlist deliberately: the
    address was just typed by whoever is registering, the content is fixed,
    and no ticket data is included."""
    from app.config import settings as env
    from app.models import Outbox

    if not env.smtp_enabled:
        return

    token = issue_verify(user.id, user.email)
    link = f"{env.app_base_url.rstrip('/')}/verify?token={token}"
    db.add(Outbox(
        to_email=user.email,
        to_name=user.display_name,
        subject="Confirm your email address",
        body=(
            f"Hello {user.display_name},\n\n"
            f"Confirm your address to finish setting up your Relay Desk account:\n\n"
            f"{link}\n\n"
            f"The link is valid for 48 hours. If you did not sign up, ignore this."
        ),
        reason="verify_email",
        status="queued",
    ))
    db.commit()


class VerifyIn(BaseModel):
    token: str


@router.post("/verify", response_model=Me)
def verify_email(payload: VerifyIn, response: Response, db: Session = Depends(get_db)):
    claims = read_verify(payload.token)
    if not claims:
        raise HTTPException(400, "That link is invalid or has expired.")

    user = db.get(User, int(claims["sub"]))
    if user is None or user.email != claims["email"]:
        raise HTTPException(400, "That link is no longer valid.")

    if not user.email_verified:
        from app import notify

        user.email_verified = True
        user.verified_at = utcnow()
        db.flush()
        notify.on_account_event(db, user, "verified")
        db.commit()
        db.refresh(user)

    _set_cookie(response, user)
    return _me(user)
