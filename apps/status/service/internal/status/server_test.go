package status

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"testing"
	"time"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

func TestPrivateAPIRequiresBoundAssertionsAndCurrentBoot(t *testing.T) {
	s := testStore(t)
	signer := protocol.Signer{Issuer: "portal", Audience: "status", AppID: "status", InstanceID: "registration", KeyID: "key", Key: bytes.Repeat([]byte{9}, 32)}
	server, err := NewServer(s, signer)
	if err != nil {
		t.Fatal(err)
	}
	viewer := protocol.Viewer{Subject: "viewer", Role: "user", OUs: []string{"team"}}
	challenge, _ := signer.NewChallenge(time.Now())
	raw, _ := json.Marshal(map[string]string{"challenge": challenge})
	req := httptest.NewRequest("POST", "/v1/handshake", bytes.NewReader(raw))
	w := httptest.NewRecorder()
	server.ServeHTTP(w, req)
	var response struct {
		Answer string `json:"answer"`
	}
	json.Unmarshal(w.Body.Bytes(), &response)
	signer.BootID, err = signer.VerifyAnswer(challenge, response.Answer, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	assertion, err := signer.Sign("GET", "/v1/components", nil, viewer, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	call := func(target *Server, token, path string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("GET", path, nil)
		r.Header.Set(protocol.Header, token)
		w := httptest.NewRecorder()
		target.ServeHTTP(w, r)
		return w
	}
	if w := call(server, "", "/v1/components"); w.Code != 401 {
		t.Fatal("unsigned request accepted")
	}
	if w := call(server, assertion, "/v1/components"); w.Code != 200 {
		t.Fatalf("read=%d %s", w.Code, w.Body.String())
	}
	if w := call(server, assertion, "/v1/components"); w.Code != 401 {
		t.Fatal("replay accepted")
	}
	next, _ := NewServer(s, signer)
	fresh, _ := signer.Sign("GET", "/v1/components", nil, viewer, time.Now())
	if w := call(next, fresh, "/v1/components"); w.Code != 401 {
		t.Fatal("old boot accepted after restart")
	}
	management, _ := signer.Sign("GET", "/v1/manage/components", nil, viewer, time.Now())
	if w := call(server, management, "/v1/manage/components"); w.Code != 403 {
		t.Fatal("reader saw management configuration")
	}
}
