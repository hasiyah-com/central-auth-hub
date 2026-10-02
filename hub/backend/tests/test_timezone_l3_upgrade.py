from unittest.mock import MagicMock

from app.security import l3_sequence as SEQ
from app.services import l3_sequence_client as CLIENT


def test_sequence_reads_only_bangkok_history():
    redis = MagicMock()
    redis.lrange.return_value = []
    assert SEQ._load_history(redis, "u") == []
    key = redis.lrange.call_args.args[0]
    assert key == "l3resid:bangkok-v1:u"
    assert key != "l3resid:u"


async def test_old_ml_service_is_rejected(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": {"point": {"available": True, "anomaly_score": .9}}}
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, json):
            assert json["feature_contract"] == "rba-23-bangkok-v1"
            return Response()
    monkeypatch.setattr(CLIENT.httpx, "AsyncClient", lambda **kw: Client())
    result = await CLIENT.evaluate_l3("u", [0.] * 23, None)
    assert result["error"] == "feature_contract_mismatch"
    assert result["point"]["available"] is False
