"""Live retry risk: recent consecutive failures per authenticator, not daily totals."""
from datetime import timedelta
from sqlalchemy import or_, func
from app.models import AuditLog, User

WINDOW_MINUTES = 10
FAILURE_METHODS = {
    'passkey_stepup_failed': 'passkey', 'stepup_totp_failed': 'totp',
    'stepup_otp_failed': 'email_otp', 'risk_force_enroll_otp_failed': 'email_otp',
    'passkey_login_failed': 'passkey', 'oauth_passkey_login_failed': 'passkey',
}
EMAIL_ACTIONS = ('passkey_login_failed', 'oauth_passkey_login_failed')
SUCCESS_METHODS = {
    'passkey_login_success': 'passkey', 'passkey_stepup_success': 'passkey',
    'stepup_totp_success': 'totp', 'stepup_otp_success': 'email_otp',
}
NEUTRAL_CODES = {'challenge_expired_or_missing', 'challenge_expired', 'challenge_used',
                 'cancelled', 'canceled', 'not_allowed_error', 'timeout'}

def consecutive_counts(events, *, post_factor_only=False):
    counts = {}
    for action, metadata, _ in events:
        metadata = metadata or {}
        method = FAILURE_METHODS.get(action)
        if action == 'risk_mfa_verify_failed':
            method = metadata.get('method') or 'unknown'
        if method:
            if metadata.get('code') in NEUTRAL_CODES:
                continue
            if post_factor_only and action in EMAIL_ACTIONS:
                continue
            counts[method] = counts.get(method, 0) + 1
            continue
        method = SUCCESS_METHODS.get(action)
        if action == 'risk_mfa_passed':
            method = metadata.get('method')
        if action == 'oauth_authorized':
            evidence = (metadata.get('breakdown') or {}).get('authentication') or {}
            if evidence.get('method') == 'passkey' and evidence.get('verified') and not evidence.get('counter_regression'):
                method = 'passkey'
        if method and not metadata.get('counter_regression'):
            counts[method] = 0
    return counts

def count_recent_consecutive_auth(db, user_id, until, *, post_factor_only=False):
    actions = tuple(FAILURE_METHODS) + tuple(SUCCESS_METHODS) + ('risk_mfa_verify_failed', 'risk_mfa_passed', 'oauth_authorized')
    attributed = [AuditLog.actor_id == user_id]
    if not post_factor_only:
        email = db.query(User.email).filter(User.id == user_id).scalar()
        if email:
            attributed.append(AuditLog.action.in_(EMAIL_ACTIONS) &
                (func.lower(AuditLog.metadata_json['email'].as_string()) == email.strip().lower()))
    events = db.query(AuditLog.action, AuditLog.metadata_json, AuditLog.created_at).filter(
        or_(*attributed), AuditLog.action.in_(actions),
        AuditLog.created_at >= until - timedelta(minutes=WINDOW_MINUTES),
        AuditLog.created_at < until,
    ).order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).all()
    return max(consecutive_counts(events, post_factor_only=post_factor_only).values(), default=0)
