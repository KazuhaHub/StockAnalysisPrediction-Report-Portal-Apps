package extensionprotocol

import (
	"testing"
	"time"
)

func TestHandshakeBindsChallengeAndFreshBoot(t *testing.T) {
	s, _, now := fixture()
	challenge, err := s.NewChallenge(now)
	if err != nil {
		t.Fatal(err)
	}
	response, err := s.AnswerChallenge(challenge, "new-boot", now)
	if err != nil {
		t.Fatal(err)
	}
	boot, err := s.VerifyAnswer(challenge, response, now)
	if err != nil || boot != "new-boot" {
		t.Fatalf("boot=%s err=%v", boot, err)
	}
	other, _ := s.NewChallenge(now)
	if _, err := s.VerifyAnswer(other, response, now); err == nil {
		t.Fatal("cross-request answer accepted")
	}
	if _, err := s.VerifyAnswer(challenge, response, now.Add(31*time.Second)); err == nil {
		t.Fatal("expired answer accepted")
	}
	s.InstanceID = "other-registration"
	if _, err := s.VerifyAnswer(challenge, response, now); err == nil {
		t.Fatal("cross-registration answer accepted")
	}
}

func TestHandshakeDoesNotAcceptForgedRequests(t *testing.T) {
	s, _, now := fixture()
	challenge, _ := s.NewChallenge(now)
	s.Audience = "other"
	if _, err := s.AnswerChallenge(challenge, "boot", now); err == nil {
		t.Fatal("wrong audience accepted")
	}
	s.Audience = "status-test"
	if _, err := s.AnswerChallenge(challenge+"x", "boot", now); err == nil {
		t.Fatal("forged challenge accepted")
	}
	if _, err := s.AnswerChallenge(challenge, "", now); err == nil {
		t.Fatal("empty boot accepted")
	}
}
