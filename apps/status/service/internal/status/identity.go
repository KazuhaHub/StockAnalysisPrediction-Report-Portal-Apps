package status

import (
	"regexp"

	protocol "github.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/packages/extensionprotocol"
)

// The platform supplies the current viewer as an opaque subject, one opaque
// identifier per actual OU ancestor and the account role. Identifiers are
// installation-scoped 64-character lowercase hex strings; they change when the
// application is reinstalled, so stored grants are bound to one installation.
var opaqueIdentifier = regexp.MustCompile(`^[0-9a-f]{64}$`)

const maxViewerOUs = 64

// authority is Status's view of a platform viewer: whether the viewer is an
// administrator and which grant principals the viewer may match.
type authority struct {
	subject    string
	admin      bool
	principals []string
}

// authorityOf adapts a platform viewer to Status's authority checks. It accepts
// only the platform's identifier shape, so a readable name or a separator
// character can never form or collide with a stored grant principal.
func authorityOf(v protocol.Viewer) (authority, bool) {
	if !opaqueIdentifier.MatchString(v.Subject) || v.Role == "" || len(v.Role) > 64 || len(v.OUs) > maxViewerOUs {
		return authority{}, false
	}
	a := authority{subject: v.Subject, admin: v.Role == "admin", principals: make([]string, 0, 1+len(v.OUs))}
	a.principals = append(a.principals, "user:"+v.Subject)
	seen := make(map[string]bool, len(v.OUs))
	for _, ou := range v.OUs {
		if !opaqueIdentifier.MatchString(ou) || seen[ou] {
			return authority{}, false
		}
		seen[ou] = true
		a.principals = append(a.principals, "ou:"+ou)
	}
	return a, true
}

func isAdmin(v protocol.Viewer) bool {
	a, ok := authorityOf(v)
	return ok && a.admin
}
