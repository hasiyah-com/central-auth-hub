"""Offline experimental auth features from attributable audit events; no live scoring change."""
import math
from datetime import timedelta, timezone

def as_utc_naive(value):
    return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)
FAIL_METHODS={'passkey_stepup_failed':'passkey','risk_mfa_verify_failed':None,'stepup_totp_failed':'totp','stepup_otp_failed':'email_otp','risk_force_enroll_otp_failed':'email_otp'}
SUCCESS_METHODS={'passkey_stepup_success':'passkey','stepup_totp_success':'totp','stepup_otp_success':'email_otp','risk_mfa_passed':None}
FAIL_ACTIONS=frozenset(FAIL_METHODS)
SUCCESS_ACTIONS=frozenset(SUCCESS_METHODS)
NEUTRAL_CODES={'challenge_expired_or_missing','challenge_expired','challenge_used','cancelled','canceled','not_allowed_error','timeout'}
FEATURE_NAMES=['log1p_failed_auth_5m','log1p_failed_auth_10m','log1p_consecutive_failed_auth_10m','failed_auth_ratio_10m','log1p_auth_attempts_10m']

def extract_failure_window_features(events,now,user_id):
    now=as_utc_naive(now);start=now-timedelta(minutes=10);eligible=[]
    for e in events:
        if e.get('actor_id') is None or str(e['actor_id'])!=str(user_id):continue
        at=as_utc_naive(e['created_at'])
        if not start<=at<now:continue
        action=e.get('action');metadata=e.get('metadata_json') or {}
        if action in FAIL_ACTIONS:
            if metadata.get('code') in NEUTRAL_CODES:continue
            method=FAIL_METHODS[action] or metadata.get('method') or 'unknown'
            eligible.append((at,method,False))
        elif action in SUCCESS_ACTIONS and not metadata.get('counter_regression'):
            method=SUCCESS_METHODS[action] or metadata.get('method')
            if method:eligible.append((at,method,True))
    eligible.sort(key=lambda x:x[0]);counts={}
    for _,method,success in eligible:counts[method]=0 if success else counts.get(method,0)+1
    failures=sum(not success for _,_,success in eligible)
    five=sum(not success and at>=now-timedelta(minutes=5) for at,_,success in eligible)
    streak=max(counts.values(),default=0)
    return [math.log1p(five),math.log1p(failures),math.log1p(streak),failures/len(eligible) if eligible else 0.0,math.log1p(len(eligible))]
