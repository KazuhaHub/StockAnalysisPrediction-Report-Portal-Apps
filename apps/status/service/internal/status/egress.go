package status

// Egress states whether the service has a way to leave its sandbox.
//
// The backend runs with no network. Probes and notification publication can only
// reach a provider through a platform broker path, which does not exist for
// background work yet. Until it does, the service is wired with NoEgress: probes
// report the unknown outcome "egress_unavailable" instead of dialling, and queued
// notices stay queued instead of consuming delivery attempts. A failed dial is
// never reported as a provider failure, so no incident is opened by a missing
// path. Neither outcome is reported as success.
//
// A broker-backed implementation replaces NoEgress when the platform grants a
// background network path; probeTransport's dial and lookup functions are the
// seams it takes over. A nil Egress keeps the direct transport used by the unit
// tests and is never configured by the service binary.
type Egress interface {
	Available() bool
}

// NoEgress is the egress of a sandbox that has no network path.
type NoEgress struct{}

func (NoEgress) Available() bool { return false }

func egressUnavailable(e Egress) bool { return e != nil && !e.Available() }
