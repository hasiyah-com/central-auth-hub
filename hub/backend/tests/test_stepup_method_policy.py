from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.routers import passkey
from app.services import mfa_policy

@pytest.mark.parametrize("p,t,email,expected",[(1,1,True,["passkey","totp"]),(1,0,True,["passkey"]),(0,1,True,["totp"]),(0,0,True,["email_otp"]),(0,0,False,[])])
def test_available_stepup_methods(monkeypatch,p,t,email,expected):
    user=SimpleNamespace(id=1,email="u@example.test")
    monkeypatch.setattr(mfa_policy.webauthn_service,"count_active",lambda *_:p)
    monkeypatch.setattr(mfa_policy.totp_service,"is_enabled",lambda *_:bool(t))
    assert mfa_policy.available_stepup_methods(user,object(),allow_email_otp_bootstrap=email)==expected

def test_email_otp_cannot_downgrade_strong_factor(monkeypatch):
    monkeypatch.setattr(mfa_policy,"available_stepup_methods",lambda *a,**k:["totp"])
    with pytest.raises(HTTPException) as exc:
        passkey._require_stepup_method(SimpleNamespace(id=1),object(),"email_otp")
    assert exc.value.status_code==403
