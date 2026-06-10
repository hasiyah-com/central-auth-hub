package session

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestSessionRoundTrip(t *testing.T) {
	mgr := NewManager([]byte("01234567890123456789012345678901"), nil, "cah_test", time.Hour, false)
	w := httptest.NewRecorder()
	want := &Session{
		AccessToken: "tok123",
		Claims:      map[string]any{"sub": "u1", "email": "a@b"},
		IssuedAt:    time.Now().Unix(),
		ExpiresAt:   time.Now().Add(time.Hour).Unix(),
	}
	if err := mgr.WriteSession(w, want); err != nil {
		t.Fatalf("write: %v", err)
	}
	cookie := w.Result().Cookies()[0]
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.AddCookie(cookie)
	got, err := mgr.ReadSession(req)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if got.AccessToken != "tok123" {
		t.Errorf("AccessToken mismatch")
	}
	if got.Claims["email"] != "a@b" {
		t.Errorf("claims missing email")
	}
}

func TestExpiredSessionRejected(t *testing.T) {
	mgr := NewManager([]byte("01234567890123456789012345678901"), nil, "cah_test", time.Hour, false)
	w := httptest.NewRecorder()
	expired := &Session{
		AccessToken: "tok",
		Claims:      map[string]any{},
		IssuedAt:    time.Now().Add(-2 * time.Hour).Unix(),
		ExpiresAt:   time.Now().Add(-1 * time.Hour).Unix(),
	}
	_ = mgr.WriteSession(w, expired)
	cookie := w.Result().Cookies()[0]
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.AddCookie(cookie)
	if _, err := mgr.ReadSession(req); err == nil {
		t.Errorf("expected expired session to error")
	}
}

func TestTamperedCookieRejected(t *testing.T) {
	mgr := NewManager([]byte("01234567890123456789012345678901"), nil, "cah_test", time.Hour, false)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.AddCookie(&http.Cookie{Name: "cah_test", Value: "tampered-garbage"})
	if _, err := mgr.ReadSession(req); err == nil {
		t.Errorf("expected tampered cookie to error")
	}
}

func TestTempStateRoundTrip(t *testing.T) {
	mgr := NewManager([]byte("01234567890123456789012345678901"), nil, "cah_test", time.Hour, false)
	w := httptest.NewRecorder()
	if err := mgr.WriteTemp(w, &TempState{State: "abc", Verifier: "xyz", ReturnTo: "/dash"}); err != nil {
		t.Fatalf("write: %v", err)
	}
	cookie := w.Result().Cookies()[0]
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.AddCookie(cookie)
	got, err := mgr.ReadTemp(req)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if got.State != "abc" || got.Verifier != "xyz" || got.ReturnTo != "/dash" {
		t.Errorf("temp state mismatch: %+v", got)
	}
}
