package status

import (
	"database/sql"
	"encoding/json"
	"regexp"
)

var billingReference = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,63}$`)

// Account references are operator-reviewed local aliases, never provider secrets.
// The balance APIs do not prove that two different keys fund different accounts.
func validateBillingIdentity(tx *sql.Tx, in ComponentInput) error {
	if !in.Enabled {
		return nil
	}
	type identity struct{ kind, credential, account, currency, site string }
	own := []identity{}
	for _, m := range in.Monitors {
		if !m.Enabled || (m.Kind != "deepseek" && m.Kind != "qwen") {
			continue
		}
		var config ProbeConfig
		if json.Unmarshal(m.Config, &config) != nil {
			return ErrInvalid
		}
		candidate := identity{m.Kind, m.CredentialID, config.AccountRef, config.Currency, config.Site}
		for _, prior := range own {
			if prior.kind != candidate.kind {
				continue
			}
			if (prior.credential == candidate.credential && prior.account != candidate.account) || (prior.account == candidate.account && (prior.currency == candidate.currency || prior.site != candidate.site)) {
				return ErrConflict
			}
		}
		own = append(own, candidate)
	}
	if len(own) == 0 {
		return nil
	}
	rows, err := tx.Query(`SELECT m.kind,m.credential_id,m.config FROM monitors m JOIN components c ON c.id=m.component_id WHERE m.kind IN('deepseek','qwen') AND m.enabled=1 AND c.enabled=1 AND m.component_id<>? LIMIT 3201`, in.ID)
	if err != nil {
		return err
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		var kind, credential, raw string
		if rows.Scan(&kind, &credential, &raw) != nil {
			return ErrInvalid
		}
		var config ProbeConfig
		if json.Unmarshal([]byte(raw), &config) != nil {
			return ErrInvalid
		}
		count++
		if count > 3200 {
			return ErrInvalid
		}
		for _, candidate := range own {
			if kind == candidate.kind && (credential == candidate.credential || config.AccountRef == candidate.account) {
				return ErrConflict
			}
		}
	}
	return rows.Err()
}
