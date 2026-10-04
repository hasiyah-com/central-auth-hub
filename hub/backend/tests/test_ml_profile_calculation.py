from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.routers import ml_admin
from app.services.feature_extraction import circular_median_hour

@pytest.mark.parametrize('trial', [False, True])
def test_profile_sources_and_midnight(monkeypatch, trial):
    monkeypatch.setattr(ml_admin.settings, 'risk_contextual_trial_enabled', trial)
    monkeypatch.setattr(ml_admin, 'get_user_profile', lambda *a: {'typical_weekend': 0})
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/154.0.0.0 Safari/537.36'
    trusted = SimpleNamespace(created_at=datetime.utcnow()-timedelta(days=1),user_agent=ua,
        decision='allow',risk_breakdown={},is_attack_ip=False,is_account_takeover=False,
        subsystem_id=None,ip='127.0.0.1',geo_country='TH',browser='Chrome 154')
    pending = SimpleNamespace(**{**trusted.__dict__, 'decision':'challenge'})
    temporal = [(datetime(2026,10,1,h)-timedelta(hours=7),) for h in [23,23,0,0,1]]
    def query(first=None, rows=None):
        q=MagicMock()
        for method in ['filter','outerjoin','order_by','limit']:
            getattr(q,method).return_value=q
        q.first.return_value=first
        q.all.return_value=rows
        return q
    db=MagicMock()
    db.query.side_effect=[query(first=SimpleNamespace(id='u',email='e',full_name='n',user_type='student')),
        query(rows=[]),query(rows=[trusted,pending]),query(rows=temporal),query(rows=[trusted,pending])]
    baseline=ml_admin.user_session_timeline('u',days=30,limit=100,admin=None,db=db)['data']['behavior_baseline']
    actual=baseline['calculation']
    assert baseline['session_count']==2
    assert actual['session_count']==(1 if trial else 2)
    assert actual['device_history_count']==1
    assert sum(x['count'] for x in actual['device_signatures'])==1
    assert actual['temporal_median_hour']==circular_median_hour([23,23,0,0,1])==0
    assert actual['weekday_count']+actual['weekend_count']==actual['session_count']
