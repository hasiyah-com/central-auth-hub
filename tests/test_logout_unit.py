"""Dependency-free regression checks for logout session selection."""
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]

class LogoutTests(unittest.TestCase):
    def run_logout(self, refresh=None, valid=True):
        tree = ast.parse((ROOT / 'hub/backend/app/routers/auth.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'logout')
        node.decorator_list = []
        node.args.defaults = []
        for arg in node.args.args:
            arg.annotation = None
        service = MagicMock()
        service.identify.return_value = refresh
        jwt = MagicMock()
        if valid:
            jwt.verify_token.return_value = {'sub': 'user', 'jti': 'exact-token', 'exp': 9999999999}
        else:
            jwt.verify_token.side_effect = ValueError('expired')
        app = types.ModuleType('app'); services = types.ModuleType('app.services')
        services.refresh_token_service = service
        modules = {'app': app, 'app.services': services, 'app.services.jwt_service': jwt}
        db = MagicMock(); session = db.query.return_value.filter.return_value.filter.return_value.first.return_value
        session.jti = 'exact-token'; session.refresh_id = 'refresh-current'
        model = MagicMock()
        env = {'LoginSession': model, 'log_action': MagicMock(), 'get_client_ip': lambda r: '127.0.0.1',
               'settings': types.SimpleNamespace(jwt_access_token_expire_minutes=15)}
        from unittest.mock import patch
        with patch.dict(sys.modules, modules):
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<logout>', 'exec'), env)
            env['logout'](None, types.SimpleNamespace(credentials='token'),
                          types.SimpleNamespace(refresh_token='raw') if refresh else None, db)
        return model, service, db, session

    def test_access_token_selects_exact_jti_not_latest_session(self):
        model, service, db, session = self.run_logout()
        model.jti.__eq__.assert_called_with('exact-token')
        db.query.return_value.filter.return_value.order_by.assert_not_called()
        self.assertIsNotNone(session.logout_at)

    def test_expired_access_uses_authenticated_refresh_session(self):
        model, service, db, session = self.run_logout(
            {'user_id': 'user', 'session_id': 'matching-session', 'refresh_id': 'verified'}, valid=False)
        model.id.__eq__.assert_called_with('matching-session')
        service.revoke.assert_any_call('verified')
        db.commit.assert_called_once()

    def test_invalid_access_does_not_select_any_session(self):
        model, service, db, session = self.run_logout(valid=False)
        db.query.assert_not_called()

if __name__ == '__main__':
    unittest.main()
