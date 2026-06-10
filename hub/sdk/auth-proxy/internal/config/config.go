// Package config — env-driven settings for cah-auth-proxy.
package config

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	HubURL              string
	ClientID            string
	ClientSecret        string
	RedirectURI         string
	Upstream            string
	Scope               []string
	Listen              string
	PathPrefix          string
	CookieName          string
	CookieSecret        []byte // 32 bytes for securecookie hash
	CookieEncryptKey    []byte // 32 bytes for securecookie block (optional)
	CookieMaxAge        time.Duration
	JWKSCacheTTL        time.Duration
	HTTPTimeout         time.Duration
	WebhookSharedKey    string
	WebhookMaxAgeSec    int
	StripIncomingAuthH  bool
}

func Load() (*Config, error) {
	c := &Config{
		HubURL:             env("CAH_HUB_URL", "http://hub-backend:8000"),
		ClientID:           env("CAH_CLIENT_ID", ""),
		ClientSecret:       env("CAH_CLIENT_SECRET", ""),
		RedirectURI:        env("CAH_REDIRECT_URI", ""),
		Upstream:           env("CAH_UPSTREAM", ""),
		Scope:              splitCSV(env("CAH_SCOPE", "openid profile email")),
		Listen:             env("CAH_LISTEN", ":8000"),
		PathPrefix:         env("CAH_PATH_PREFIX", "/cah-auth"),
		CookieName:         env("CAH_COOKIE_NAME", "cah_session"),
		CookieMaxAge:       envDuration("CAH_COOKIE_MAX_AGE", time.Hour),
		JWKSCacheTTL:       envDuration("CAH_JWKS_CACHE_TTL", 10*time.Minute),
		HTTPTimeout:        envDuration("CAH_HTTP_TIMEOUT", 10*time.Second),
		WebhookSharedKey:   env("CAH_WEBHOOK_SHARED_KEY", ""),
		WebhookMaxAgeSec:   envInt("CAH_WEBHOOK_MAX_AGE_SEC", 300),
		StripIncomingAuthH: envBool("CAH_STRIP_INCOMING_AUTH_HEADERS", true),
	}

	if c.ClientID == "" {
		return nil, fmt.Errorf("config: CAH_CLIENT_ID is required")
	}
	if c.ClientSecret == "" {
		return nil, fmt.Errorf("config: CAH_CLIENT_SECRET is required")
	}
	if c.RedirectURI == "" {
		return nil, fmt.Errorf("config: CAH_REDIRECT_URI is required")
	}
	if c.Upstream == "" {
		return nil, fmt.Errorf("config: CAH_UPSTREAM is required")
	}

	secret := env("CAH_COOKIE_SECRET", "")
	if secret == "" {
		// auto-generate (dev only — warn in logs)
		buf := make([]byte, 32)
		_, _ = rand.Read(buf)
		c.CookieSecret = buf // pragma: allowlist secret
	} else {
		b, err := hex.DecodeString(secret)
		if err != nil || len(b) < 32 {
			return nil, fmt.Errorf("CAH_COOKIE_SECRET: must be hex-encoded 32+ bytes (got %d)", len(b))
		}
		c.CookieSecret = b[:32]
	}

	if encKey := env("CAH_COOKIE_ENCRYPT_KEY", ""); encKey != "" {
		b, err := hex.DecodeString(encKey)
		if err != nil || len(b) != 32 {
			return nil, fmt.Errorf("CAH_COOKIE_ENCRYPT_KEY: must be hex-encoded 32 bytes")
		}
		c.CookieEncryptKey = b
	}

	return c, nil
}

func env(key, fallback string) string {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	return v
}

func envDuration(key string, fallback time.Duration) time.Duration {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		return fallback
	}
	return d
}

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	i, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return i
}

func envBool(key string, fallback bool) bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv(key)))
	if v == "" {
		return fallback
	}
	return v == "true" || v == "1" || v == "yes"
}

func splitCSV(s string) []string {
	parts := strings.FieldsFunc(s, func(r rune) bool {
		return r == ',' || r == ' '
	})
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
