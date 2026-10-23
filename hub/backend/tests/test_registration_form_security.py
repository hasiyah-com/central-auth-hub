from app.routers.oauth import _registration_html


def test_registration_form_is_token_bound_and_cannot_choose_global_role():
    html = _registration_html(
        token="secret-registration-token",
        email="student@uni.ac.th",
        full_name="Student One",
        subsystem_name="Library",
        nonce="nonce-1",
    )
    assert 'action="/oauth/register"' in html
    assert 'name="registration_token" value="secret-registration-token"' in html
    assert 'name="identifier"' in html
    assert 'name="faculty"' in html
    assert 'name="user_type"' not in html
    assert 'nonce="nonce-1"' in html


def test_registration_form_escapes_google_and_subsystem_values():
    html = _registration_html(
        token='"><script>alert(1)</script>',
        email='<img src=x onerror=alert(1)>@uni.ac.th',
        full_name='<script>alert(1)</script>',
        subsystem_name='<svg onload=alert(1)>',
        nonce="safe-nonce",
    )
    assert "<script>alert(1)</script>" not in html
    assert "<svg onload=alert(1)>" not in html
    assert "&lt;script&gt;" in html
