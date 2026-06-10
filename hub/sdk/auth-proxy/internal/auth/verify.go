package auth

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/lestrrat-go/jwx/v2/jwk"
	"github.com/lestrrat-go/jwx/v2/jwt"
)

// Verifier — JWT verify ผ่าน JWKS (auto refresh via jwk.Cache).
type Verifier struct {
	disc     *Discovery
	clientID string
	leeway   time.Duration

	mu      sync.RWMutex
	cache   *jwk.Cache
	jwksURI string
	bgCtx   context.Context
}

func NewVerifier(disc *Discovery, clientID string, jwksTTL time.Duration) *Verifier {
	return &Verifier{
		disc:     disc,
		clientID: clientID,
		leeway:   30 * time.Second,
		bgCtx:    context.Background(),
	}
}

// Verify — decode + verify signature/aud/iss/exp. Returns parsed claims.
func (v *Verifier) Verify(ctx context.Context, token string) (jwt.Token, error) {
	doc, err := v.disc.Get(ctx)
	if err != nil {
		return nil, fmt.Errorf("verify: discovery: %w", err)
	}

	keyset, err := v.ensureJWKS(ctx, doc.JWKSURI)
	if err != nil {
		return nil, fmt.Errorf("verify: jwks: %w", err)
	}

	parsed, err := jwt.Parse(
		[]byte(token),
		jwt.WithKeySet(keyset),
		jwt.WithIssuer(doc.Issuer),
		jwt.WithAudience(v.clientID),
		jwt.WithAcceptableSkew(v.leeway),
		jwt.WithValidate(true),
	)
	if err != nil {
		return nil, fmt.Errorf("verify: %w", err)
	}
	if exp := parsed.Expiration(); !exp.IsZero() && time.Now().After(exp.Add(v.leeway)) {
		return nil, fmt.Errorf("verify: token expired")
	}
	return parsed, nil
}

// ParseUnverified — for testing/diagnostics only (do NOT trust claims).
func ParseUnverified(token string) (jwt.Token, error) {
	t, err := jwt.Parse([]byte(token), jwt.WithVerify(false), jwt.WithValidate(false))
	if err != nil {
		return nil, err
	}
	return t, nil
}

func (v *Verifier) ensureJWKS(ctx context.Context, uri string) (jwk.Set, error) {
	v.mu.RLock()
	if v.cache != nil && v.jwksURI == uri {
		c := v.cache
		v.mu.RUnlock()
		return c.Get(ctx, uri)
	}
	v.mu.RUnlock()

	v.mu.Lock()
	defer v.mu.Unlock()
	if v.cache != nil && v.jwksURI == uri {
		return v.cache.Get(ctx, uri)
	}

	c := jwk.NewCache(v.bgCtx)
	if err := c.Register(uri,
		jwk.WithMinRefreshInterval(30*time.Second),
		jwk.WithRefreshInterval(10*time.Minute),
	); err != nil {
		return nil, fmt.Errorf("jwks cache register: %w", err)
	}
	// trigger initial fetch
	if _, err := c.Refresh(ctx, uri); err != nil {
		return nil, fmt.Errorf("jwks cache refresh: %w", err)
	}
	v.cache = c
	v.jwksURI = uri
	return c.Get(ctx, uri)
}
