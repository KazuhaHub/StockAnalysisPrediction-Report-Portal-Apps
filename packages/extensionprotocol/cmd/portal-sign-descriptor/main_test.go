package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The descriptor, public key and envelope below are the shared Go/TypeScript publisher-signature
// corpus case "exact" of the Portal (internal/appplatform/testdata/publisher-signatures.json). The
// signing key is the published RFC 8032 test key 1 seed: public test material that must never be
// enrolled anywhere. Ed25519 is deterministic, so signing the corpus descriptor with it has to
// reproduce the Portal corpus envelope byte for byte.
const rfc8032Seed = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
const corpusPublicKey = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"
const corpusDescriptorBase64 = "ewogICJmb3JtYXQiOiAicG9ydGFsLmFwcC92MiIsCiAgImlkIjogIm5vdGVzLXNhbXBsZSIsCiAgInZlcnNpb24iOiAiMS4wLjAtYmV0YS4xIiwKICAicHVibGlzaGVyIjogImV4YW1wbGUtcHVibGlzaGVyIiwKICAiY29tcGF0aWJpbGl0eSI6IHsKICAgICJwbGF0Zm9ybV9hcGkiOiAiPj0yLjAuMCA8My4wLjAiLAogICAgInJ1bm5lcl9wcm90b2NvbCI6ICI+PTEuMC4wIDwyLjAuMCIKICB9LAogICJwcmVzZW50YXRpb24iOiB7CiAgICAibmFtZV9rZXkiOiAiYXBwLm5hbWUiLAogICAgImRlc2NyaXB0aW9uX2tleSI6ICJhcHAuZGVzY3JpcHRpb24iLAogICAgImVudHJ5IjogImluZGV4Lmh0bWwiLAogICAgImxvY2FsZXMiOiBbCiAgICAgICJlbi1VUyIsCiAgICAgICJ6aC1DTiIsCiAgICAgICJ6aC1UVyIKICAgIF0sCiAgICAicm91dGVzIjogWwogICAgICB7CiAgICAgICAgImlkIjogImhvbWUiLAogICAgICAgICJwYXRoIjogIi8iLAogICAgICAgICJsYXlvdXQiOiAiZG9jdW1lbnQiCiAgICAgIH0KICAgIF0KICB9LAogICJmcm9udGVuZCI6IHsKICAgICJhcnRpZmFjdCI6ICJ1aS56aXAiLAogICAgInNoYTI1NiI6ICJhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhIgogIH0sCiAgImNhcGFiaWxpdGllcyI6IHsKICAgICJyZXF1aXJlZCI6IFsKICAgICAgInN0b3JhZ2UuZmlsZXMiCiAgICBdLAogICAgIm9wdGlvbmFsIjogWwogICAgICAibm90aWZpY2F0aW9ucy5wdWJsaXNoIgogICAgXQogIH0sCiAgImRhdGEiOiB7CiAgICAic2NoZW1hIjogMSwKICAgICJyZWFkYWJsZV9zY2hlbWFzIjogWwogICAgICAxCiAgICBdLAogICAgIndyaXRlc19vbl9zdGFydHVwIjogZmFsc2UKICB9Cn0K"
const corpusEnvelopeBase64 = "eyJmb3JtYXQiOiJwb3J0YWwuYXBwLnNpZ25hdHVyZS8xLWRldi4xIiwiYWxnb3JpdGhtIjoiRWQyNTUxOSIsInB1Ymxpc2hlciI6ImV4YW1wbGUtcHVibGlzaGVyIiwia2V5X2lkIjoidGVzdC1rZXktMSIsImRlc2NyaXB0b3Jfc2hhMjU2IjoiYWRjZDc4NmI3NzdjZmVhMjRmN2E5MWJjMGY3YmYyNDU5ZTk0OWYyOThhZDU2ZmI3ZWU5ZjdlNmE1NTg2N2MwOSIsInNpZ25hdHVyZSI6IkRVcWtwZ2tmMjZPVHprSUJMSzJHM0ZCb0QxbVJlZG52NlJObVd5NkV5WXd1UXozZXdvY25EODJXMkhHWGludDg4VGpudXdULWVSRkljTUJlX1hpZ0JBIn0="

func corpusDescriptor(t *testing.T) []byte {
	t.Helper()
	raw, err := base64.StdEncoding.DecodeString(corpusDescriptorBase64)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func corpusEnvelope(t *testing.T) []byte {
	t.Helper()
	raw, err := base64.StdEncoding.DecodeString(corpusEnvelopeBase64)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

// invoke runs the tool and returns its exit code and both output streams.
func invoke(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	var out, errOut bytes.Buffer
	code := run(args, &out, &errOut)
	return code, out.String(), errOut.String()
}

func write(t *testing.T, path string, data []byte, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(path, data, mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
}

func writeCorpusSeed(t *testing.T, dir string) string {
	t.Helper()
	seed, _ := hex.DecodeString(rfc8032Seed)
	path := filepath.Join(dir, "corpus.key")
	write(t, path, []byte(base64.RawURLEncoding.EncodeToString(seed)+"\n"), 0o600)
	return path
}

func TestKeygenWritesPrivateKeyAndPrintsEnrollmentValues(t *testing.T) {
	dir := t.TempDir()
	keyPath := filepath.Join(dir, "release.key")
	code, out, errOut := invoke(t, "keygen", "--key-id", "release-2026", "--private-key", keyPath)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	info, err := os.Stat(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode %o", info.Mode().Perm())
	}
	raw, _ := os.ReadFile(keyPath)
	seed, err := base64.RawURLEncoding.Strict().DecodeString(strings.TrimSpace(string(raw)))
	if err != nil || len(seed) != ed25519.SeedSize {
		t.Fatalf("private key file is not a 32 byte base64url seed: %v", err)
	}
	public := base64.RawURLEncoding.EncodeToString(ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey))
	fingerprint := sha256.Sum256(ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey))
	for _, want := range []string{`"id": "release-2026"`, `"public_key": "` + public + `"`, hex.EncodeToString(fingerprint[:])} {
		if !strings.Contains(out, want) {
			t.Fatalf("output lacks %q:\n%s", want, out)
		}
	}
	if len(public) != 43 {
		t.Fatalf("public key length %d", len(public))
	}
	// The seed is never printed.
	if strings.Contains(out+errOut, strings.TrimSpace(string(raw))) {
		t.Fatal("private key leaked to output")
	}
}

func TestKeygenNeverOverwrites(t *testing.T) {
	dir := t.TempDir()
	keyPath := filepath.Join(dir, "release.key")
	write(t, keyPath, []byte("existing\n"), 0o600)
	code, _, errOut := invoke(t, "keygen", "--key-id", "release-2026", "--private-key", keyPath)
	if code == 0 || !strings.Contains(errOut, "exists") {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	if raw, _ := os.ReadFile(keyPath); string(raw) != "existing\n" {
		t.Fatalf("existing file changed: %q", raw)
	}
	// A dangling symlink is not followed to create a file elsewhere.
	link := filepath.Join(dir, "link.key")
	target := filepath.Join(dir, "elsewhere.key")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	if code, _, _ = invoke(t, "keygen", "--key-id", "release-2026", "--private-key", link); code == 0 {
		t.Fatal("wrote through a symlink")
	}
	if _, err := os.Stat(target); err == nil {
		t.Fatal("symlink target created")
	}
}

func TestKeygenRejectsBadKeyID(t *testing.T) {
	dir := t.TempDir()
	for _, id := range []string{"", "Release", "-x", "a b", strings.Repeat("a", 129)} {
		keyPath := filepath.Join(dir, "k-"+id[:min(len(id), 4)])
		if code, _, _ := invoke(t, "keygen", "--key-id", id, "--private-key", keyPath); code == 0 {
			t.Fatalf("key id %q accepted", id)
		}
		if _, err := os.Stat(keyPath); err == nil {
			t.Fatalf("key written for %q", id)
		}
	}
}

func TestSignReproducesPortalCorpusEnvelope(t *testing.T) {
	dir := t.TempDir()
	descriptor := filepath.Join(dir, "descriptor.json")
	write(t, descriptor, corpusDescriptor(t), 0o644)
	signaturePath := filepath.Join(dir, "descriptor.sig")
	code, _, errOut := invoke(t, "sign", "--descriptor", descriptor, "--private-key", writeCorpusSeed(t, dir), "--key-id", "test-key-1", "--out", signaturePath)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	got, _ := os.ReadFile(signaturePath)
	if !bytes.Equal(got, corpusEnvelope(t)) {
		t.Fatalf("envelope differs from the Portal corpus:\n%s\n%s", got, corpusEnvelope(t))
	}
	if code, out, errOut := invoke(t, "verify", "--descriptor", descriptor, "--signature", signaturePath, "--public-key", corpusPublicKey); code != 0 || !strings.Contains(out, "ok") {
		t.Fatalf("verify exit %d: %s %s", code, out, errOut)
	}
}

func TestVerifyAcceptsPortalCorpusEnvelope(t *testing.T) {
	dir := t.TempDir()
	descriptor := filepath.Join(dir, "descriptor.json")
	signaturePath := filepath.Join(dir, "descriptor.sig")
	write(t, descriptor, corpusDescriptor(t), 0o644)
	write(t, signaturePath, corpusEnvelope(t), 0o644)
	if code, _, errOut := invoke(t, "verify", "--descriptor", descriptor, "--signature", signaturePath, "--public-key", corpusPublicKey, "--key-id", "test-key-1"); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
}

// generated signs a fresh descriptor with a freshly generated key through the tool itself.
func generated(t *testing.T) (dir, descriptor, signaturePath, public string) {
	t.Helper()
	dir = t.TempDir()
	keyPath := filepath.Join(dir, "release.key")
	code, out, errOut := invoke(t, "keygen", "--key-id", "release-2026", "--private-key", keyPath)
	if code != 0 {
		t.Fatalf("keygen: %s", errOut)
	}
	for _, line := range strings.Split(out, "\n") {
		if rest, ok := strings.CutPrefix(strings.TrimSpace(line), `"public_key": "`); ok {
			public = strings.TrimSuffix(strings.TrimSuffix(rest, ","), `"`)
		}
	}
	if len(public) != 43 {
		t.Fatalf("no public key in output:\n%s", out)
	}
	descriptor = filepath.Join(dir, "descriptor.json")
	write(t, descriptor, corpusDescriptor(t), 0o644)
	signaturePath = filepath.Join(dir, "descriptor.sig")
	if code, _, errOut = invoke(t, "sign", "--descriptor", descriptor, "--private-key", keyPath, "--key-id", "release-2026", "--out", signaturePath); code != 0 {
		t.Fatalf("sign: %s", errOut)
	}
	return
}

func TestSignThenVerifyWithGeneratedKey(t *testing.T) {
	_, descriptor, signaturePath, public := generated(t)
	if code, _, errOut := invoke(t, "verify", "--descriptor", descriptor, "--signature", signaturePath, "--public-key", public, "--key-id", "release-2026"); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
}

func TestVerifyRejections(t *testing.T) {
	dir, descriptor, signaturePath, public := generated(t)
	other := filepath.Join(dir, "other.key")
	_, out, _ := invoke(t, "keygen", "--key-id", "other", "--private-key", other)
	var otherPublic string
	for _, line := range strings.Split(out, "\n") {
		if rest, ok := strings.CutPrefix(strings.TrimSpace(line), `"public_key": "`); ok {
			otherPublic = strings.TrimSuffix(strings.TrimSuffix(rest, ","), `"`)
		}
	}
	raw, _ := os.ReadFile(descriptor)
	tampered := filepath.Join(dir, "tampered.json")
	write(t, tampered, bytes.Replace(raw, []byte("notes-sample"), []byte("notes-sampl3"), 1), 0o644)
	envelope, _ := os.ReadFile(signaturePath)
	edit := func(name, from, to string) string {
		path := filepath.Join(dir, name)
		write(t, path, bytes.Replace(envelope, []byte(from), []byte(to), 1), 0o644)
		return path
	}
	flipped := []byte(string(envelope))
	i := bytes.Index(flipped, []byte(`"signature":"`)) + len(`"signature":"`)
	if flipped[i] == 'A' {
		flipped[i] = 'B'
	} else {
		flipped[i] = 'A'
	}
	badSignature := filepath.Join(dir, "badsig.sig")
	write(t, badSignature, flipped, 0o644)
	cases := map[string][]string{
		"tampered descriptor": {"--descriptor", tampered, "--signature", signaturePath, "--public-key", public},
		"wrong public key":    {"--descriptor", descriptor, "--signature", signaturePath, "--public-key", otherPublic},
		"wrong key id":        {"--descriptor", descriptor, "--signature", signaturePath, "--public-key", public, "--key-id", "other"},
		"tampered signature":  {"--descriptor", descriptor, "--signature", badSignature, "--public-key", public},
		"wrong publisher":     {"--descriptor", descriptor, "--signature", edit("pub.sig", "example-publisher", "other-publisher"), "--public-key", public},
		"wrong digest":        {"--descriptor", descriptor, "--signature", edit("digest.sig", `"descriptor_sha256":"`, `"descriptor_sha256":"0`), "--public-key", public},
		"wrong format":        {"--descriptor", descriptor, "--signature", edit("format.sig", "signature/1-dev.1", "signature/2"), "--public-key", public},
		"algorithm":           {"--descriptor", descriptor, "--signature", edit("alg.sig", "Ed25519", "Ed448"), "--public-key", public},
		"unknown field":       {"--descriptor", descriptor, "--signature", edit("extra.sig", `{"format"`, `{"extra":"x","format"`), "--public-key", public},
		"duplicate field":     {"--descriptor", descriptor, "--signature", edit("dup.sig", `{"format"`, `{"format":"portal.app.signature/1-dev.1","format"`), "--public-key", public},
		"bad public key":      {"--descriptor", descriptor, "--signature", signaturePath, "--public-key", public[:42]},
		"padded public key":   {"--descriptor", descriptor, "--signature", signaturePath, "--public-key", public + "="},
		"missing descriptor":  {"--descriptor", filepath.Join(dir, "none.json"), "--signature", signaturePath, "--public-key", public},
	}
	for name, args := range cases {
		t.Run(name, func(t *testing.T) {
			if code, _, _ := invoke(t, append([]string{"verify"}, args...)...); code == 0 {
				t.Fatal("accepted")
			}
		})
	}
}

func TestSignRefusals(t *testing.T) {
	dir := t.TempDir()
	keyPath := writeCorpusSeed(t, dir)
	descriptor := filepath.Join(dir, "descriptor.json")
	write(t, descriptor, corpusDescriptor(t), 0o644)
	args := func(extra ...string) []string {
		return append([]string{"sign", "--descriptor", descriptor, "--private-key", keyPath, "--key-id", "test-key-1"}, extra...)
	}
	t.Run("existing output", func(t *testing.T) {
		out := filepath.Join(dir, "exists.sig")
		write(t, out, []byte("keep"), 0o644)
		if code, _, _ := invoke(t, args("--out", out)...); code == 0 {
			t.Fatal("overwrote")
		}
		if raw, _ := os.ReadFile(out); string(raw) != "keep" {
			t.Fatal("existing signature changed")
		}
	})
	t.Run("permissive key file", func(t *testing.T) {
		open := filepath.Join(dir, "open.key")
		raw, _ := os.ReadFile(keyPath)
		write(t, open, raw, 0o644)
		out := filepath.Join(dir, "open.sig")
		code, _, errOut := invoke(t, "sign", "--descriptor", descriptor, "--private-key", open, "--key-id", "test-key-1", "--out", out)
		if code == 0 || !strings.Contains(errOut, "permissions") {
			t.Fatalf("exit %d: %s", code, errOut)
		}
		if _, err := os.Stat(out); err == nil {
			t.Fatal("signature written")
		}
	})
	t.Run("malformed key file", func(t *testing.T) {
		bad := filepath.Join(dir, "bad.key")
		write(t, bad, []byte("not a key\n"), 0o600)
		if code, _, _ := invoke(t, "sign", "--descriptor", descriptor, "--private-key", bad, "--key-id", "test-key-1", "--out", filepath.Join(dir, "bad.sig")); code == 0 {
			t.Fatal("accepted")
		}
	})
	raw := corpusDescriptor(t)
	bad := map[string][]byte{
		"not json":          []byte("nope"),
		"wrong format":      bytes.Replace(raw, []byte("portal.app/v2"), []byte("portal.app/v1"), 1),
		"bad publisher":     bytes.Replace(raw, []byte(`"example-publisher"`), []byte(`"Example"`), 1),
		"missing publisher": bytes.Replace(raw, []byte(`"publisher": "example-publisher",`), nil, 1),
		"duplicate key":     bytes.Replace(raw, []byte(`"version"`), []byte(`"id": "x", "version"`), 1),
		"nested duplicate":  bytes.Replace(raw, []byte(`"schema": 1,`), []byte(`"schema": 1, "schema": 2,`), 1),
		"byte order mark":   append([]byte("\xef\xbb\xbf"), raw...),
		"trailing json":     append(append([]byte{}, raw...), []byte("{}")...),
		"oversized":         append(append([]byte(`{"format":"portal.app/v2","publisher":"p","pad":"`), bytes.Repeat([]byte("a"), 131072)...), []byte(`"}`)...),
	}
	for name, content := range bad {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(dir, strings.ReplaceAll(name, " ", "-")+".json")
			write(t, path, content, 0o644)
			out := filepath.Join(dir, strings.ReplaceAll(name, " ", "-")+".sig")
			if code, _, _ := invoke(t, "sign", "--descriptor", path, "--private-key", keyPath, "--key-id", "test-key-1", "--out", out); code == 0 {
				t.Fatal("signed")
			}
			if _, err := os.Stat(out); err == nil {
				t.Fatal("signature written")
			}
		})
	}
	t.Run("bad key id", func(t *testing.T) {
		if code, _, _ := invoke(t, "sign", "--descriptor", descriptor, "--private-key", keyPath, "--key-id", "Bad", "--out", filepath.Join(dir, "k.sig")); code == 0 {
			t.Fatal("accepted")
		}
	})
}

func TestUsage(t *testing.T) {
	for _, args := range [][]string{{}, {"unknown"}, {"sign"}, {"verify", "--bogus"}, {"keygen"}} {
		if code, _, _ := invoke(t, args...); code == 0 {
			t.Fatalf("%v accepted", args)
		}
	}
}
