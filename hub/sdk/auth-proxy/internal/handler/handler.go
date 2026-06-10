// Package handler — HTTP handlers (login, callback, logout, webhook, proxy).
package handler

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/central-auth-hub/auth-proxy/internal/auth"
	"github.com/central-auth-hub/auth-proxy/internal/config"
	"github.com/central-auth-hub/auth-proxy/internal/session"
)

type Server struct {
	Cfg       *config.Config
	Disc      *auth.Discovery
	Verifier  *auth.Verifier
	Sessions  *session.Manager
	Logger    func(string, ...any)
	revokedAt map[string]int64 // hub_user_id → unix when revoked
	rxIPProxy *httputil.ReverseProxy
}

func New(cfg *config.Config, disc *auth.Discovery, verifier *auth.Verifier, sessions *session.Manager, logger func(string, ...any)) (*Server, error) {
	upstream, err := url.Parse(cfg.Upstream)
	if err != nil {
		return nil, fmt.Errorf("bad upstream URL: %w", err)
	}
	rp := httputil.NewSingleHostReverseProxy(upstream)
	// preserve original Host
	origDirector := rp.Director
	rp.Director = func(r *http.Request) {
		origDirector(r)
		r.Host = upstream.Host
	}
	return &Server{
		Cfg:       cfg,
		Disc:      disc,
		Verifier:  verifier,
		Sessions:  sessions,
		Logger:    logger,
		revokedAt: map[string]int64{},
		rxIPProxy: rp,
	}, nil
}

// ── /cah-auth/login — start OAuth ──

func (s *Server) HandleLogin(w http.ResponseWriter, r *http.Request) {
	disc, err := s.Disc.Get(r.Context())
	if err != nil {
		http.Error(w, "discovery: "+err.Error(), http.StatusBadGateway)
		return
	}
	state, err := auth.GenerateState()
	if err != nil {
		http.Error(w, "state generation failed", http.StatusInternalServerError)
		return
	}
	verifier, err := auth.GenerateVerifier(64)
	if err != nil {
		http.Error(w, "pkce generation failed", http.StatusInternalServerError)
		return
	}
	challenge := auth.ChallengeFor(verifier)

	returnTo := r.URL.Query().Get("return_to")
	if returnTo == "" {
		returnTo = "/"
	}

	if err := s.Sessions.WriteTemp(w, &session.TempState{
		State:    state,
		Verifier: verifier,
		ReturnTo: returnTo,
		IssuedAt: time.Now().Unix(),
	}); err != nil {
		http.Error(w, "session write failed", http.StatusInternalServerError)
		return
	}

	params := url.Values{
		"client_id":             {s.Cfg.ClientID},
		"redirect_uri":          {s.Cfg.RedirectURI},
		"response_type":         {"code"},
		"scope":                 {strings.Join(s.Cfg.Scope, " ")},
		"state":                 {state},
		"code_challenge":        {challenge},
		"code_challenge_method": {"S256"},
	}
	http.Redirect(w, r, disc.AuthorizationEndpoint+"?"+params.Encode(), http.StatusFound)
}

// ── /cah-auth/callback — exchange + verify ──

func (s *Server) HandleCallback(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if e := q.Get("error"); e != "" {
		http.Error(w, "Hub returned error: "+e, http.StatusBadRequest)
		return
	}
	code := q.Get("code")
	receivedState := q.Get("state")
	if code == "" || receivedState == "" {
		http.Error(w, "missing code or state", http.StatusBadRequest)
		return
	}
	temp, err := s.Sessions.ReadTemp(r)
	if err != nil {
		http.Error(w, "no oauth state in session (session expired?)", http.StatusBadRequest)
		return
	}
	s.Sessions.ClearTemp(w)

	if err := auth.VerifyState(temp.State, receivedState); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	disc, err := s.Disc.Get(r.Context())
	if err != nil {
		http.Error(w, "discovery: "+err.Error(), http.StatusBadGateway)
		return
	}

	// exchange
	form := url.Values{
		"grant_type":    {"authorization_code"},
		"code":          {code},
		"client_id":     {s.Cfg.ClientID},
		"client_secret": {s.Cfg.ClientSecret},
		"redirect_uri":  {s.Cfg.RedirectURI},
		"code_verifier": {temp.Verifier},
	}
	ctx, cancel := context.WithTimeout(r.Context(), s.Cfg.HTTPTimeout)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, disc.TokenEndpoint, strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		http.Error(w, "token endpoint unreachable", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		http.Error(w, fmt.Sprintf("token exchange HTTP %d: %s", resp.StatusCode, string(body)[:min(200, len(body))]), http.StatusBadGateway)
		return
	}
	var tokResp struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.Unmarshal(body, &tokResp); err != nil || tokResp.AccessToken == "" {
		http.Error(w, "no access_token in response", http.StatusBadGateway)
		return
	}

	// verify JWT
	tok, err := s.Verifier.Verify(r.Context(), tokResp.AccessToken)
	if err != nil {
		http.Error(w, "jwt verify: "+err.Error(), http.StatusUnauthorized)
		return
	}

	claims := map[string]any{}
	for k, v := range tok.PrivateClaims() {
		claims[k] = v
	}
	if sub := tok.Subject(); sub != "" {
		claims["sub"] = sub
	}
	if iss := tok.Issuer(); iss != "" {
		claims["iss"] = iss
	}
	if auds := tok.Audience(); len(auds) > 0 {
		claims["aud"] = auds[0]
	}
	if exp := tok.Expiration(); !exp.IsZero() {
		claims["exp"] = exp.Unix()
	}
	if jti := tok.JwtID(); jti != "" {
		claims["jti"] = jti
	}

	expAt := tok.Expiration()
	if expAt.IsZero() {
		expAt = time.Now().Add(s.Cfg.CookieMaxAge)
	}
	if err := s.Sessions.WriteSession(w, &session.Session{
		AccessToken: tokResp.AccessToken,
		Claims:      claims,
		IssuedAt:    time.Now().Unix(),
		ExpiresAt:   expAt.Unix(),
	}); err != nil {
		http.Error(w, "session write failed", http.StatusInternalServerError)
		return
	}

	target := temp.ReturnTo
	if target == "" || !strings.HasPrefix(target, "/") {
		target = "/"
	}
	http.Redirect(w, r, target, http.StatusFound)
}

// ── /cah-auth/logout ──

func (s *Server) HandleLogout(w http.ResponseWriter, r *http.Request) {
	s.Sessions.ClearSession(w)
	target := r.URL.Query().Get("return_to")
	if target == "" || !strings.HasPrefix(target, "/") {
		target = "/"
	}
	http.Redirect(w, r, target, http.StatusFound)
}

// ── /cah-auth/webhook/access-revoked ──

func (s *Server) HandleWebhook(w http.ResponseWriter, r *http.Request) {
	if s.Cfg.WebhookSharedKey == "" {
		http.Error(w, "webhook not configured", http.StatusUnauthorized)
		return
	}
	sig := r.Header.Get("X-Hub-Signature-256")
	ts := r.Header.Get("X-Hub-Timestamp")
	if sig == "" || ts == "" {
		http.Error(w, "missing signature/timestamp", http.StatusUnauthorized)
		return
	}
	tsInt, err := strconv.ParseInt(ts, 10, 64)
	if err != nil {
		http.Error(w, "bad timestamp", http.StatusUnauthorized)
		return
	}
	now := time.Now().Unix()
	if now-tsInt > int64(s.Cfg.WebhookMaxAgeSec) || tsInt-now > int64(s.Cfg.WebhookMaxAgeSec) {
		http.Error(w, "timestamp out of tolerance", http.StatusUnauthorized)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB cap
	if err != nil {
		http.Error(w, "read body failed", http.StatusBadRequest)
		return
	}
	mac := hmac.New(sha256.New, []byte(s.Cfg.WebhookSharedKey))
	mac.Write(body)
	expected := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(expected), []byte(sig)) {
		http.Error(w, "signature mismatch", http.StatusUnauthorized)
		return
	}

	var payload struct {
		Event     string `json:"event"`
		HubUserID string `json:"hub_user_id"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if payload.Event == "access_revoked" && payload.HubUserID != "" {
		s.revokedAt[payload.HubUserID] = time.Now().Unix()
		s.Logger("webhook access_revoked: user=%s", payload.HubUserID)
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

// ── Reverse proxy with header injection ──

const (
	HeaderUserSub     = "X-Hub-User-Sub"
	HeaderUserEmail   = "X-Hub-User-Email"
	HeaderUserName    = "X-Hub-User-Name"
	HeaderUserType    = "X-Hub-User-Type"
	HeaderUserRole    = "X-Hub-User-Role"
	HeaderUserFaculty = "X-Hub-User-Faculty"
	HeaderUserMajor   = "X-Hub-User-Major"
	HeaderUserStudent = "X-Hub-User-Student-ID"
	HeaderUserEmpID   = "X-Hub-User-Employee-ID"
	HeaderUserPhone   = "X-Hub-User-Phone"
	HeaderUserExp     = "X-Hub-User-Exp"
)

// AllInjectedHeaders — strip these from incoming requests (security).
var AllInjectedHeaders = []string{
	HeaderUserSub, HeaderUserEmail, HeaderUserName, HeaderUserType,
	HeaderUserRole, HeaderUserFaculty, HeaderUserMajor,
	HeaderUserStudent, HeaderUserEmpID, HeaderUserPhone, HeaderUserExp,
}

func (s *Server) HandleProxy(w http.ResponseWriter, r *http.Request) {
	// 1. ALWAYS strip incoming X-Hub-User-* headers (กัน client forge)
	if s.Cfg.StripIncomingAuthH {
		for _, h := range AllInjectedHeaders {
			r.Header.Del(h)
		}
	}

	// 2. ตรวจ session
	sess, err := s.Sessions.ReadSession(r)
	if err != nil {
		// not authenticated — redirect to login with return_to
		returnTo := r.URL.Path
		if r.URL.RawQuery != "" {
			returnTo += "?" + r.URL.RawQuery
		}
		http.Redirect(w, r, s.Cfg.PathPrefix+"/login?return_to="+url.QueryEscape(returnTo), http.StatusFound)
		return
	}

	// 3. ตรวจ revocation list
	sub, _ := sess.Claims["sub"].(string)
	if sub != "" {
		if revokedAt, ok := s.revokedAt[sub]; ok {
			if int64(sess.IssuedAt) < revokedAt {
				s.Sessions.ClearSession(w)
				http.Redirect(w, r, s.Cfg.PathPrefix+"/login", http.StatusFound)
				return
			}
		}
	}

	// 4. Inject headers from claims
	setIfString(r, HeaderUserSub, sess.Claims["sub"])
	setIfString(r, HeaderUserEmail, sess.Claims["email"])
	setIfString(r, HeaderUserName, sess.Claims["name"])
	setIfString(r, HeaderUserType, sess.Claims["user_type"])
	setIfString(r, HeaderUserRole, sess.Claims["role_in_subsystem"])
	setIfString(r, HeaderUserFaculty, sess.Claims["faculty"])
	setIfString(r, HeaderUserMajor, sess.Claims["major"])
	setIfString(r, HeaderUserStudent, sess.Claims["student_id"])
	setIfString(r, HeaderUserEmpID, sess.Claims["employee_id"])
	setIfString(r, HeaderUserPhone, sess.Claims["phone"])
	if exp, ok := sess.Claims["exp"]; ok {
		r.Header.Set(HeaderUserExp, fmt.Sprintf("%v", exp))
	}

	// 5. Forward
	s.rxIPProxy.ServeHTTP(w, r)
}

func setIfString(r *http.Request, key string, v any) {
	if s, ok := v.(string); ok && s != "" {
		r.Header.Set(key, s)
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
