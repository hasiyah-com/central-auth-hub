// cah-auth-proxy — Central Auth Hub sidecar/proxy.
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/central-auth-hub/auth-proxy/internal/auth"
	"github.com/central-auth-hub/auth-proxy/internal/config"
	"github.com/central-auth-hub/auth-proxy/internal/handler"
	"github.com/central-auth-hub/auth-proxy/internal/session"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}
	log.Printf("cah-auth-proxy starting · upstream=%s · path_prefix=%s · listen=%s",
		cfg.Upstream, cfg.PathPrefix, cfg.Listen)

	disc := auth.NewDiscovery(cfg.HubURL, cfg.JWKSCacheTTL, cfg.HTTPTimeout)
	verifier := auth.NewVerifier(disc, cfg.ClientID, cfg.JWKSCacheTTL)

	secure := strings.HasPrefix(cfg.RedirectURI, "https://")
	sessions := session.NewManager(cfg.CookieSecret, cfg.CookieEncryptKey,
		cfg.CookieName, cfg.CookieMaxAge, secure)

	srv, err := handler.New(cfg, disc, verifier, sessions, log.Printf)
	if err != nil {
		log.Fatalf("init handler: %v", err)
	}

	r := chi.NewRouter()
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))

	// Health (always 200 — for orchestrator probes)
	r.Get("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte("ok"))
	})

	// Auth endpoints under path prefix
	prefix := cfg.PathPrefix
	r.Route(prefix, func(rt chi.Router) {
		rt.Get("/login", srv.HandleLogin)
		rt.Get("/callback", srv.HandleCallback)
		rt.Get("/logout", srv.HandleLogout)
		rt.Post("/webhook/access-revoked", srv.HandleWebhook)
	})

	// Catch-all → reverse proxy (with header injection)
	r.HandleFunc("/*", srv.HandleProxy)

	httpSrv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           r,
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Graceful shutdown
	go func() {
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	log.Printf("shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(ctx)
}
