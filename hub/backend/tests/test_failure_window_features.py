from datetime import datetime,timedelta,timezone
import math
from app.services.failure_window_features import extract_failure_window_features
NOW=datetime(2026,1,1,12,tzinfo=timezone.utc)
def event(minutes,action='risk_mfa_verify_failed',actor='u'):
    return dict(created_at=NOW-timedelta(minutes=minutes),action=action,actor_id=actor,metadata_json={"method":"totp"})

def test_windows_and_success_reset():
    features=extract_failure_window_features([event(9),event(6),event(4),event(3,'risk_mfa_passed'),event(2),event(1)],NOW,'u')
    assert features==[math.log1p(3),math.log1p(5),math.log1p(2),5/6,math.log1p(6)]

def test_unknown_or_unattributed_events_do_not_raise_risk():
    events=[event(1,actor=None),event(1,actor='other'),event(1,'passkey_login_failed'),event(1,'would_block')]
    assert extract_failure_window_features(events,NOW,'u')==[0,0,0,0,0]

def test_current_future_and_old_events_excluded():
    assert extract_failure_window_features([event(0),event(-1),event(11)],NOW,'u')==[0,0,0,0,0]

def test_window_boundaries_and_timezone_are_consistent():
    events=[event(5),event(10)]
    expected=[math.log1p(1),math.log1p(2),math.log1p(2),1,math.log1p(2)]
    assert extract_failure_window_features(events,NOW,'u')==expected
    assert extract_failure_window_features(events,NOW.astimezone(timezone(timedelta(hours=7))),'u')==expected

def test_legitimate_retry_then_success_has_no_streak():
    features=extract_failure_window_features([event(3),event(2),event(1),event(.5,'stepup_totp_success')],NOW,'u')
    assert features[2]==0 and features[3]==.75


def test_success_resets_only_same_method():
    events=[event(3,'passkey_stepup_failed'),event(2,'stepup_totp_failed'),event(1,'stepup_totp_success')]
    assert extract_failure_window_features(events,NOW,'u')[2]==math.log1p(1)

def test_cancellation_and_counter_regression_are_not_success_evidence():
    cancelled=event(2);cancelled['metadata_json']['code']='cancelled'
    success=event(1,'stepup_totp_success');success['metadata_json']['counter_regression']=True
    assert extract_failure_window_features([cancelled],NOW,'u')==[0,0,0,0,0]
    assert extract_failure_window_features([event(3),success],NOW,'u')[2]==math.log1p(1)
