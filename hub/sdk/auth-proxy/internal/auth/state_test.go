package auth

import (
	"regexp"
	"testing"
)

func TestGenerateStateHex(t *testing.T) {
	s, err := GenerateState()
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if !regexp.MustCompile(`^[0-9a-f]{32}$`).MatchString(s) {
		t.Errorf("state not 32 hex: %q", s)
	}
}

func TestVerifyStateMatch(t *testing.T) {
	if err := VerifyState("abc123", "abc123"); err != nil {
		t.Errorf("matching state should pass: %v", err)
	}
}

func TestVerifyStateMismatch(t *testing.T) {
	if err := VerifyState("expected", "attacker"); err == nil {
		t.Errorf("mismatch should error")
	}
}

func TestVerifyStateEmpty(t *testing.T) {
	if err := VerifyState("", "anything"); err == nil {
		t.Errorf("empty expected should error")
	}
}

func TestVerifyStateDiffLen(t *testing.T) {
	if err := VerifyState("short", "longer-value"); err == nil {
		t.Errorf("different-length should error")
	}
}

func TestVerifyStateSameLenDiffer(t *testing.T) {
	if err := VerifyState("abcd1234", "abcd1235"); err == nil {
		t.Errorf("same-length different should error")
	}
}
