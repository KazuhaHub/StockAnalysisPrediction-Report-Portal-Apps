package status

import (
	"crypto/sha256"
	"encoding/hex"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

// The platform supplies opaque, installation-scoped identifiers: a 64-character
// lowercase hex subject and one such identifier per actual OU ancestor. Fixtures
// derive the same shape from readable names so tests stay legible.
func fixtureOpaque(purpose, name string) string {
	sum := sha256.Sum256([]byte("status-fixture\x00" + purpose + "\x00" + name))
	return hex.EncodeToString(sum[:])
}

func fixtureViewer(role, name string, ous ...string) protocol.Viewer {
	viewer := protocol.Viewer{Subject: fixtureOpaque("account", name), Role: role, OUs: []string{}}
	for _, ou := range ous {
		viewer.OUs = append(viewer.OUs, fixtureOpaque("ou", ou))
	}
	return viewer
}

func fixtureAdmin() protocol.Viewer { return fixtureViewer("admin", "admin") }

// fixtureOU is the grant principal for a fixture OU.
func fixtureOU(name string) string { return "ou:" + fixtureOpaque("ou", name) }
