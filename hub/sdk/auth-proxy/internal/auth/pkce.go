package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
)

// GenerateVerifier — RFC 7636 §4.1, length 43..128.
func GenerateVerifier(length int) (string, error) {
	if length < 43 || length > 128 {
		return "", fmt.Errorf("verifier length must be 43..128")
	}
	buf := make([]byte, length)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64URL(buf), nil
}

// ChallengeFor — RFC 7636 §4.2: BASE64URL(SHA256(verifier)).
func ChallengeFor(verifier string) string {
	h := sha256.Sum256([]byte(verifier))
	return base64URL(h[:])
}

func base64URL(b []byte) string {
	return base64.RawURLEncoding.EncodeToString(b)
}
