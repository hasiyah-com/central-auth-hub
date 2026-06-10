// Package session — sealed cookie storage (encrypted + authenticated).
package session

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/gorilla/securecookie"
)

// State stored in the session cookie.
type Session struct {
	AccessToken string            `json:"at"`
	Claims      map[string]any    `json:"c"`
	IssuedAt    int64             `json:"iat"`
	ExpiresAt   int64             `json:"exp"`
}

// TempState — used during OAuth flow (between login + callback).
type TempState struct {
	State    string `json:"s"`
	Verifier string `json:"v"`
	ReturnTo string `json:"r"`
	IssuedAt int64  `json:"iat"`
}

type Manager struct {
	sc         *securecookie.SecureCookie
	cookieName string
	tempName   string
	maxAge     time.Duration
	secure     bool
}

func NewManager(hashKey, blockKey []byte, cookieName string, maxAge time.Duration, secure bool) *Manager {
	sc := securecookie.New(hashKey, blockKey)
	sc.MaxAge(int(maxAge.Seconds()))
	return &Manager{
		sc:         sc,
		cookieName: cookieName,
		tempName:   cookieName + "_tmp",
		maxAge:     maxAge,
		secure:     secure,
	}
}

// ── Session (long-lived after login) ──

func (m *Manager) WriteSession(w http.ResponseWriter, s *Session) error {
	enc, err := m.sc.Encode(m.cookieName, s)
	if err != nil {
		return err
	}
	http.SetCookie(w, &http.Cookie{
		Name:     m.cookieName,
		Value:    enc,
		Path:     "/",
		MaxAge:   int(m.maxAge.Seconds()),
		HttpOnly: true,
		Secure:   m.secure,
		SameSite: http.SameSiteLaxMode,
	})
	return nil
}

func (m *Manager) ReadSession(r *http.Request) (*Session, error) {
	c, err := r.Cookie(m.cookieName)
	if err != nil {
		return nil, err
	}
	var s Session
	if err := m.sc.Decode(m.cookieName, c.Value, &s); err != nil {
		return nil, err
	}
	if s.ExpiresAt > 0 && time.Now().Unix() > s.ExpiresAt {
		return nil, errors.New("session expired")
	}
	return &s, nil
}

func (m *Manager) ClearSession(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     m.cookieName,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		HttpOnly: true,
		Secure:   m.secure,
		SameSite: http.SameSiteLaxMode,
	})
}

// ── Temp state (during OAuth flow) ──

func (m *Manager) WriteTemp(w http.ResponseWriter, t *TempState) error {
	enc, err := m.sc.Encode(m.tempName, t)
	if err != nil {
		return err
	}
	http.SetCookie(w, &http.Cookie{
		Name:     m.tempName,
		Value:    enc,
		Path:     "/",
		MaxAge:   600, // 10 min should be enough for OAuth flow
		HttpOnly: true,
		Secure:   m.secure,
		SameSite: http.SameSiteLaxMode,
	})
	return nil
}

func (m *Manager) ReadTemp(r *http.Request) (*TempState, error) {
	c, err := r.Cookie(m.tempName)
	if err != nil {
		return nil, err
	}
	var t TempState
	if err := m.sc.Decode(m.tempName, c.Value, &t); err != nil {
		return nil, err
	}
	return &t, nil
}

func (m *Manager) ClearTemp(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     m.tempName,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		HttpOnly: true,
		Secure:   m.secure,
		SameSite: http.SameSiteLaxMode,
	})
}

// Marshal/Unmarshal helpers for debug logging only.
func (s *Session) String() string {
	b, _ := json.Marshal(s)
	return string(b)
}
