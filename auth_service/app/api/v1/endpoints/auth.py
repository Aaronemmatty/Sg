"""Authentication endpoints — all public and authenticated auth flows."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthRequired, get_current_user
from app.core.logging import get_logger
from app.db.session import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MfaChallengeResponse,
    MfaDisableRequest,
    MfaEnableRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    OkResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    LogoutRequest,
    TokenResponse,
    UserProfile,
    VerifyEmailRequest,
)
from app.services.auth import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])
log = get_logger(__name__)


def _auth_svc(db: AsyncSession, request: Request) -> AuthService:
    return AuthService(db=db, request=request)


# ── Registration ──────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegisterResponse:
    svc = _auth_svc(db, request)
    try:
        user = await svc.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            tenant_slug=body.tenant_slug,
        )
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)

    from app.core.config import get_settings
    settings = get_settings()
    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        requires_email_verification=settings.EMAIL_VERIFICATION_REQUIRED,
        message="Registration successful. Check your email to verify your account."
        if settings.EMAIL_VERIFICATION_REQUIRED
        else "Registration successful.",
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse | MfaChallengeResponse,
    summary="Login with email + password",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse | MfaChallengeResponse:
    svc = _auth_svc(db, request)
    try:
        result = await svc.login(
            email=body.email,
            password=body.password,
            tenant_slug=body.tenant_slug,
            request=request,
            device_name=body.device_name,
        )
    except AuthError as e:
        status_code = (
            status.HTTP_423_LOCKED if e.code == "account_locked"
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(status_code=status_code, detail=e.message)

    if result.get("mfa_required"):
        return MfaChallengeResponse(
            challenge_id=result["challenge_id"],
            mfa_type=result["mfa_type"],
        )
    return TokenResponse(**result)


@router.post(
    "/mfa/verify",
    response_model=TokenResponse,
    summary="Complete MFA challenge",
)
async def verify_mfa(
    body: MfaVerifyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    svc = _auth_svc(db, request)
    try:
        result = await svc.verify_mfa_and_login(
            challenge_id=body.challenge_id,
            code=body.code,
            request=request,
        )
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.message)
    return TokenResponse(**result)


# ── Token lifecycle ───────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    svc = _auth_svc(db, request)
    try:
        result = await svc.refresh_tokens(refresh_token=body.refresh_token, request=request)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.message)
    return TokenResponse(**result)


@router.post("/logout", response_model=OkResponse, summary="Logout current session")
async def logout(
    body: LogoutRequest,
    current: AuthRequired,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    await svc.logout(
        refresh_token=body.refresh_token,
        user_id=current.user.id,
        everywhere=body.everywhere,
    )
    return OkResponse(message="Logged out successfully.")


# ── Password ──────────────────────────────────────────────────────────────────

@router.post("/password/change", response_model=OkResponse, summary="Change password")
async def change_password(
    body: ChangePasswordRequest,
    current: AuthRequired,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    try:
        await svc.change_password(
            user=current.user,
            old_password=body.old_password,
            new_password=body.new_password,
        )
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    return OkResponse(message="Password changed. All sessions revoked.")


@router.post(
    "/password/forgot",
    response_model=OkResponse,
    summary="Request password reset email",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    background_tasks.add_task(
        svc.forgot_password,
        email=body.email,
        tenant_slug=body.tenant_slug,
        request=request,
    )
    return OkResponse(message="If the email exists, a reset link has been sent.")


@router.post("/password/reset", response_model=OkResponse, summary="Reset password via token")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    try:
        await svc.reset_password(token=body.token, new_password=body.new_password)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    return OkResponse(message="Password reset successful.")


# ── Email verification ────────────────────────────────────────────────────────

@router.post("/email/verify", response_model=OkResponse, summary="Verify email address")
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    try:
        await svc.verify_email(token=body.token)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    return OkResponse(message="Email verified successfully.")


@router.post(
    "/email/resend-verification",
    response_model=OkResponse,
    summary="Resend verification email",
)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    await svc.resend_verification(email=body.email, tenant_slug=body.tenant_slug)
    return OkResponse(message="If the account exists and is unverified, a new link was sent.")


# ── MFA management ────────────────────────────────────────────────────────────

@router.post("/mfa/setup", response_model=MfaSetupResponse, summary="Begin MFA setup (get TOTP secret)")
async def mfa_setup(
    current: AuthRequired,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MfaSetupResponse:
    svc = _auth_svc(db, request)
    try:
        data = await svc.setup_mfa(user=current.user)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    return MfaSetupResponse(**data)


@router.post("/mfa/enable", response_model=OkResponse, summary="Confirm and enable MFA")
async def mfa_enable(
    body: MfaEnableRequest,
    current: AuthRequired,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    try:
        await svc.enable_mfa(user=current.user, code=body.code)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    return OkResponse(message="MFA enabled. Store your backup codes securely.")


@router.post("/mfa/disable", response_model=OkResponse, summary="Disable MFA")
async def mfa_disable(
    body: MfaDisableRequest,
    current: AuthRequired,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OkResponse:
    svc = _auth_svc(db, request)
    try:
        await svc.disable_mfa(user=current.user, code=body.code, password=body.password)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    return OkResponse(message="MFA disabled.")


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfile, summary="Get current user profile")
async def get_me(current: AuthRequired) -> UserProfile:
    u = current.user
    return UserProfile(
        user_id=u.id,
        email=u.email,
        display_name=u.display_name,
        tenant_id=u.tenant_id,
        roles=current.roles,
        permissions=current.permissions,
        mfa_enabled=u.mfa_enabled,
        email_verified=u.preferences.get("email_verified", False),
        created_at=u.created_at,
    )
