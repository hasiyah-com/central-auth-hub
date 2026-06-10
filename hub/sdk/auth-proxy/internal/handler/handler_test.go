package handler

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/central-auth-hub/auth-proxy/internal/auth"
	"github.com/central-auth-hub/auth-proxy/internal/config"
	"github.com/central-auth-hub/auth-proxy/internal/session"
)

func newTestServer(t *testing.T, modify func(*config.Config)) (*Server, *config.Config) {
	t.Helper()
	cfg := &config.Config{
		HubURL:             "http://hub-test",
		ClientID:           "cli_test",
		ClientSecret:       "sec_test",
		RedirectURI:        "http://proxy.test/cah-auth/callback",
		Upstream:           "http://upstream.test",
		Scope:              []string{"openid", "profile", "email"},
		Listen:             ":0",
		PathPrefix:         "/cah-auth",
		CookieName:         "cah_session",
		CookieSecret:       []byte("01234567890123456789012345678901"),
		CookieMaxAge:       time.Hour,
		JWKSCacheTTL:       10 * time.Minute,
		HTTPTimeout:        5 * time.Second,
		WebhookSharedKey:   "shared-test-key",
		WebhookMaxAgeSec:   300,
		StripIncomingAuthH: true,
	}
	if modify != nil {
		modify(cfg)
	}
	disc := auth.NewDiscovery(cfg.HubURL, cfg.JWKSCacheTTL, cfg.HTTPTimeout)
	v := auth.NewVerifier(disc, cfg.ClientID, cfg.JWKSCacheTTL)
	mgr := session.NewManager(cfg.CookieSecret, nil, cfg.CookieName, cfg.CookieMaxAge, false)
	srv, err := New(cfg, disc, v, mgr, func(string, ...any) {})
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	return srv, cfg
}

func signBody(key, body string) string {
	mac := hmac.New(sha256.New, []byte(key))
	mac.Write([]byte(body))
	return hex.EncodeToString(mac.Sum(nil))
}

// ── Webhook ──

func TestWebhookValidSignature(t *testing.T) {
	srv, cfg := newTestServer(t, nil)
	body := `{"event":"access_revoked","hub_user_id":"u1"}`
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	req := httptest.NewRequest(http.MethodPost, "/cah-auth/webhook/access-revoked", io.NopCloser(stringReader(body)))
	req.Header.Set("X-Hub-Signature-256", signBody(cfg.WebhookSharedKey, body))
	req.Header.Set("X-Hub-Timestamp", ts)
	w := httptest.NewRecorder()
	srv.HandleWebhook(w, req)
	if w.Code != 200 {
		t.Errorf("expected 200, got %d body=%s", w.Code, w.Body.String())
	}
	if srv.revokedAt["u1"] == 0 {
		t.Errorf("user u1 not in revoked list")
	}
}

func TestWebhookBadSignature(t *testing.T) {
	srv, _ := newTestServer(t, nil)
	body := `{"x":1}`
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	req := httptest.NewRequest(http.MethodPost, "/cah-auth/webhook/access-revoked", io.NopCloser(stringReader(body)))
	req.Header.Set("X-Hub-Signature-256", "00000000000000000000000000000000")
	req.Header.Set("X-Hub-Timestamp", ts)
	w := httptest.NewRecorder()
	srv.HandleWebhook(w, req)
	if w.Code != 401 {
		t.Errorf("expected 401, got %d", w.Code)
	}
}

func TestWebhookExpiredTimestamp(t *testing.T) {
	srv, cfg := newTestServer(t, nil)
	body := `{"x":1}`
	ts := strconv.FormatInt(time.Now().Unix()-600, 10)
	req := httptest.NewRequest(http.MethodPost, "/cah-auth/webhook/access-revoked", io.NopCloser(stringReader(body)))
	req.Header.Set("X-Hub-Signature-256", signBody(cfg.WebhookSharedKey, body))
	req.Header.Set("X-Hub-Timestamp", ts)
	w := httptest.NewRecorder()
	srv.HandleWebhook(w, req)
	if w.Code != 401 {
		t.Errorf("expected 401, got %d", w.Code)
	}
}

func TestWebhookMissingHeaders(t *testing.T) {
	srv, _ := newTestServer(t, nil)
	req := httptest.NewRequest(http.MethodPost, "/cah-auth/webhook/access-revoked", io.NopCloser(stringReader(`{}`)))
	w := httptest.NewRecorder()
	srv.HandleWebhook(w, req)
	if w.Code != 401 {
		t.Errorf("expected 401, got %d", w.Code)
	}
}

func TestWebhookNotConfigured(t *testing.T) {
	srv, _ := newTestServer(t, func(c *config.Config) {
		c.WebhookSharedKey = ""
	})
	req := httptest.NewRequest(http.MethodPost, "/cah-auth/webhook/access-revoked", io.NopCloser(stringReader(`{}`)))
	req.Header.Set("X-Hub-Signature-256", "x")
	req.Header.Set("X-Hub-Timestamp", "1")
	w := httptest.NewRecorder()
	srv.HandleWebhook(w, req)
	if w.Code != 401 {
		t.Errorf("expected 401, got %d", w.Code)
	}
}

// ── Proxy (no session = redirect; session = forward with headers) ──

func TestProxyNoSessionRedirectsToLogin(t *testing.T) {
	srv, cfg := newTestServer(t, nil)
	req := httptest.NewRequest(http.MethodGet, "/protected/page?x=1", nil)
	w := httptest.NewRecorder()
	srv.HandleProxy(w, req)
	if w.Code != 302 {
		t.Errorf("expected 302, got %d", w.Code)
	}
	loc := w.Header().Get("Location")
	if !contains(loc, cfg.PathPrefix+"/login") {
		t.Errorf("expected redirect to login, got %s", loc)
	}
	if !contains(loc, "return_to=") {
		t.Errorf("expected return_to in URL, got %s", loc)
	}
}

func TestProxyStripsIncomingHubHeaders(t *testing.T) {
	srv, _ := newTestServer(t, nil)
	// session not set → it will redirect; but check that headers were stripped first
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	for _, h := range AllInjectedHeaders {
		req.Header.Set(h, "attacker-value")
	}
	w := httptest.NewRecorder()
	srv.HandleProxy(w, req)
	for _, h := range AllInjectedHeaders {
		if req.Header.Get(h) != "" {
			t.Errorf("header %s should be stripped, got %s", h, req.Header.Get(h))
		}
	}
}

// helpers

func contains(s, substr string) bool {
	for i := 0; i+len(substr) <= len(s); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

type strReader struct {
	s string
	i int
}

func stringReader(s string) *strReader { return &strReader{s: s} }
func (r *strReader) Read(p []byte) (int, error) {
	if r.i >= len(r.s) {
		return 0, io.EOF
	}
	n := copy(p, r.s[r.i:])
	r.i += n
	return n, nil
}

// ensure encoding/json + unused suppression
var _ = json.Marshal
