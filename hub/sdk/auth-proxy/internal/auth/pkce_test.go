package auth

import (
	"regexp"
	"testing"
)

func TestGenerateVerifierLength(t *testing.T) {
	v, err := GenerateVerifier(64)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(v) < 43 || len(v) > 128 {
		t.Errorf("verifier length %d out of range", len(v))
	}
}

func TestGenerateVerifierCharset(t *testing.T) {
	v, _ := GenerateVerifier(64)
	if !regexp.MustCompile(`^[A-Za-z0-9_-]+$`).MatchString(v) {
		t.Errorf("verifier has invalid chars: %q", v)
	}
}

func TestGenerateVerifierUnique(t *testing.T) {
	a, _ := GenerateVerifier(64)
	b, _ := GenerateVerifier(64)
	if a == b {
		t.Errorf("two verifiers identical")
	}
}

func TestGenerateVerifierRejectShort(t *testing.T) {
	_, err := GenerateVerifier(32)
	if err == nil {
		t.Errorf("expected error for length=32")
	}
}

func TestGenerateVerifierRejectLong(t *testing.T) {
	_, err := GenerateVerifier(200)
	if err == nil {
		t.Errorf("expected error for length=200")
	}
}

// RFC 7636 §4.2 Appendix B test vector
func TestChallengeMatchesRFC7636Vector(t *testing.T) {
	verifier := "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk" // pragma: allowlist secret
	want := "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"   // pragma: allowlist secret
	got := ChallengeFor(verifier)
	if got != want {
		t.Errorf("RFC 7636 vector mismatch:\n  got:  %s\n  want: %s", got, want)
	}
}

func TestChallengeDeterministic(t *testing.T) {
	if ChallengeFor("abc123") != ChallengeFor("abc123") {
		t.Errorf("challenge not deterministic")
	}
}
