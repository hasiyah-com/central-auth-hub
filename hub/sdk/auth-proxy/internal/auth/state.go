package auth

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
)

// GenerateState — 32 hex chars (16 bytes).
func GenerateState() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// VerifyState — constant-time compare via subtle.ConstantTimeCompare.
func VerifyState(expected, provided string) error {
	if expected == "" {
		return fmt.Errorf("no state to verify (session expired?)")
	}
	a := []byte(expected)
	b := []byte(provided)
	if len(a) != len(b) || subtle.ConstantTimeCompare(a, b) != 1 {
		return fmt.Errorf("state mismatch (possible CSRF)")
	}
	return nil
}
