package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
)

// Routes:
//
//	GET  /health/ready     readiness, no identity
//	POST /v1/handshake     boot handshake with Portal, no identity (signed by the registration key)
//	POST /v1/tasks/run     background task from Portal, service identity (not a viewer)
//	GET  /v1/hello         example viewer route, needs a verified X-Portal-Assertion
//
// Every other /v1/ path is a viewer route you add; copy the hello handler. The
// path spaces /v1/public/, /v1/ingress/ and /v1/machine/ are reserved for
// capabilities this app does not declare (see docs/backend-service-v2.md), so
// they answer 404 here and never reach viewer handling.
//
// The platform relay accepts response bodies up to 1 MiB.

const (
	maxResponse = 1 << 20
	maxTaskBody = 12288
)

var reservedSpaces = []string{"/v1/public/", "/v1/ingress/", "/v1/machine/"}

type server struct {
	queue *Queue
	auth  *authority
}

func newServer(queue *Queue, auth *authority) *server {
	return &server{queue: queue, auth: auth}
}

func (s *server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Portal never forwards cookies or credentials; refuse them rather than ignore them.
	if r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" {
		writeError(w, http.StatusBadRequest, "refused")
		return
	}
	for _, space := range reservedSpaces {
		if strings.HasPrefix(r.URL.Path, space) {
			writeError(w, http.StatusNotFound, "not_found")
			return
		}
	}
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/health/ready":
		if r.URL.RawQuery != "" {
			writeError(w, http.StatusBadRequest, "refused")
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"protocol": "portal.backend/1", "ready": true, "data_format": "1"})
	case r.Method == http.MethodPost && r.URL.Path == "/v1/handshake":
		s.handshake(w, r)
	case r.Method == http.MethodPost && r.URL.Path == "/v1/tasks/run":
		s.task(w, r)
	case r.Method == http.MethodGet && r.URL.Path == "/v1/hello":
		claims, err := s.auth.verifyViewer(r.Header.Get("X-Portal-Assertion"), r.Method, r.URL.RequestURI(), nil)
		if err != nil {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		// The assertion carries the viewer's role and opaque OU identifiers.
		// Authorize with them per request; never cache them across requests.
		writeJSON(w, http.StatusOK, map[string]string{"greeting": "hello", "role": claims.Viewer.Role})
	default:
		writeError(w, http.StatusNotFound, "not_found")
	}
}

func (s *server) handshake(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" || r.Header.Get("Content-Type") != "application/json" {
		writeError(w, http.StatusBadRequest, "refused")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, 8193))
	var req struct {
		Challenge string `json:"challenge"`
	}
	if err != nil || len(raw) == 0 || len(raw) > 8192 || strictJSON(raw, &req) != nil ||
		req.Challenge == "" || len(req.Challenge) > 4096 {
		writeError(w, http.StatusBadRequest, "refused")
		return
	}
	answer, err := s.auth.answerChallenge(req.Challenge)
	if err != nil {
		writeError(w, http.StatusConflict, "registration_unavailable")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"answer": answer})
}

// task accepts a background task. Portal gives a task 45 seconds, so this
// handler only validates and enqueues, then answers at once; the work runs in
// the queue's worker (tasks.go) and must be idempotent. A transient refusal is
// answered with outcome retry, a permanent one with failed.
func (s *server) task(w http.ResponseWriter, r *http.Request) {
	if r.URL.RawQuery != "" || r.Header.Get("Content-Type") != "application/json" ||
		r.Header.Get("X-Portal-Assertion") != "" {
		taskFailure(w, "run_request_invalid")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, maxTaskBody+1))
	var req taskRequest
	if err != nil || len(raw) == 0 || len(raw) > maxTaskBody || strictJSON(raw, &req) != nil ||
		req.Format != taskRequestFormat || req.TaskID == "" || len(req.TaskID) > 128 ||
		req.OccurrenceID == "" || len(req.OccurrenceID) > 128 {
		taskFailure(w, "run_request_invalid")
		return
	}
	if s.auth.validateServiceIdentity(r.Header.Get("X-Portal-Service-Identity"), "tasks.schedule") != nil {
		taskFailure(w, "run_authority_invalid")
		return
	}
	var payload struct {
		Job string `json:"job"`
	}
	if strictJSON(req.Payload, &payload) != nil || payload.Job == "" {
		taskFailure(w, "run_payload_invalid")
		return
	}
	duplicate, err := s.queue.Submit(payload.Job, req.TaskID, req.OccurrenceID)
	switch {
	case errors.Is(err, errUnknownJob):
		taskFailure(w, "run_payload_invalid")
		return
	case errors.Is(err, errConflict):
		taskFailure(w, "run_identity_conflict")
		return
	case errors.Is(err, errQueueFull):
		// Transient: ask Portal to deliver the same occurrence again later.
		taskRetry(w, "run_queue_full")
		return
	case err != nil:
		taskRetry(w, "run_unavailable")
		return
	}
	result, _ := json.Marshal(map[string]any{"job": payload.Job, "duplicate": duplicate})
	sum := sha256.Sum256(result)
	writeJSON(w, http.StatusOK, taskResponse{Format: taskResponseFormat, Outcome: "succeeded",
		Result: result, EvidenceSHA256: hex.EncodeToString(sum[:])})
}

// taskFailure ends the task: Portal will not deliver this occurrence again.
func taskFailure(w http.ResponseWriter, code string) {
	writeJSON(w, http.StatusOK, taskResponse{Format: taskResponseFormat, Outcome: "failed", ErrorCode: code})
}

// taskRetry is for a refusal that may pass: Portal delivers the same occurrence
// again after its backoff, up to its attempt limit, then marks the task failed.
// The other outcomes a response may carry are succeeded and uncertain.
func taskRetry(w http.ResponseWriter, code string) {
	writeJSON(w, http.StatusOK, taskResponse{Format: taskResponseFormat, Outcome: "retry", ErrorCode: code})
}

func writeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]string{"error": code})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	raw, err := json.Marshal(value)
	if err != nil {
		status, raw = http.StatusUnprocessableEntity, []byte(`{"error":"unencodable"}`)
	} else if len(raw) > maxResponse {
		status, raw = http.StatusUnprocessableEntity, []byte(`{"error":"response_too_large"}`)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}
