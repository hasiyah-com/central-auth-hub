// Package auth — OIDC Discovery + JWKS + PKCE + state + JWT verify
package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"
)

// DiscoveryDoc — OIDC Discovery 1.0 §3.
type DiscoveryDoc struct {
	Issuer                            string   `json:"issuer"`
	AuthorizationEndpoint             string   `json:"authorization_endpoint"`
	TokenEndpoint                     string   `json:"token_endpoint"`
	UserinfoEndpoint                  string   `json:"userinfo_endpoint"`
	JWKSURI                           string   `json:"jwks_uri"`
	IntrospectionEndpoint             string   `json:"introspection_endpoint"`
	ScopesSupported                   []string `json:"scopes_supported"`
	ResponseTypesSupported            []string `json:"response_types_supported"`
	IDTokenSigningAlgValuesSupported  []string `json:"id_token_signing_alg_values_supported"`
	CodeChallengeMethodsSupported     []string `json:"code_challenge_methods_supported"`
}

// Discovery — fetch + memory cache for OIDC discovery doc.
type Discovery struct {
	hubURL  string
	ttl     time.Duration
	timeout time.Duration

	mu     sync.RWMutex
	doc    *DiscoveryDoc
	loaded time.Time
}

func NewDiscovery(hubURL string, ttl, timeout time.Duration) *Discovery {
	return &Discovery{hubURL: hubURL, ttl: ttl, timeout: timeout}
}

func (d *Discovery) Get(ctx context.Context) (*DiscoveryDoc, error) {
	d.mu.RLock()
	if d.doc != nil && time.Since(d.loaded) < d.ttl {
		doc := d.doc
		d.mu.RUnlock()
		return doc, nil
	}
	d.mu.RUnlock()

	d.mu.Lock()
	defer d.mu.Unlock()
	// re-check after lock
	if d.doc != nil && time.Since(d.loaded) < d.ttl {
		return d.doc, nil
	}

	url := d.hubURL + "/.well-known/openid-configuration"
	reqCtx, cancel := context.WithTimeout(ctx, d.timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("discovery: build request: %w", err)
	}
	req.Header.Set("Accept", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("discovery: fetch: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("discovery: HTTP %d", resp.StatusCode)
	}

	var doc DiscoveryDoc
	if err := json.NewDecoder(resp.Body).Decode(&doc); err != nil {
		return nil, fmt.Errorf("discovery: decode: %w", err)
	}
	if doc.Issuer == "" || doc.JWKSURI == "" {
		return nil, fmt.Errorf("discovery: missing required fields")
	}
	d.doc = &doc
	d.loaded = time.Now()
	return &doc, nil
}
