// Command portal-sign-descriptor creates a publisher signing key and signs, and checks, the detached
// signature (descriptor.sig) of a portal.app/v2 descriptor in the framing the Portal verifies.
//
//	portal-sign-descriptor keygen --key-id ID --private-key FILE
//	portal-sign-descriptor sign   --descriptor FILE --private-key FILE --key-id ID --out FILE
//	portal-sign-descriptor verify --descriptor FILE --signature FILE --public-key KEY [--key-id ID]
//
// The signature is Ed25519 over "portal.app/descriptor/v2" || 0x00 || uint64_be(len) || the exact
// descriptor bytes. Nothing here enrolls a key: an administrator does that in the Portal.
package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
	"unicode/utf8"
)

const (
	envelopeFormat     = "portal.app.signature/1-dev.1"
	descriptorFormat   = "portal.app/v2"
	frameDomain        = "portal.app/descriptor/v2\x00"
	maxDescriptorBytes = 131072
	maxEnvelopeBytes   = 4096
	maxKeyFileBytes    = 256
)

var (
	publisherPattern = regexp.MustCompile(`^[a-z][a-z0-9-]{0,63}$`)
	keyIDPattern     = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,127}$`)
	digestPattern    = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

const usage = `usage:
  portal-sign-descriptor keygen --key-id ID --private-key FILE
  portal-sign-descriptor sign   --descriptor FILE --private-key FILE --key-id ID --out FILE
  portal-sign-descriptor verify --descriptor FILE --signature FILE --public-key KEY [--key-id ID]
`

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(stderr, usage)
		return 2
	}
	var err error
	switch args[0] {
	case "keygen":
		err = keygen(args[1:], stdout, stderr)
	case "sign":
		err = sign(args[1:], stdout, stderr)
	case "verify":
		err = verify(args[1:], stdout, stderr)
	default:
		fmt.Fprint(stderr, usage)
		return 2
	}
	if err != nil {
		fmt.Fprintln(stderr, "portal-sign-descriptor:", err)
		if errors.Is(err, errUsage) {
			return 2
		}
		return 1
	}
	return 0
}

var errUsage = errors.New("invalid arguments")

func flags(name string, stderr io.Writer) *flag.FlagSet {
	set := flag.NewFlagSet(name, flag.ContinueOnError)
	set.SetOutput(stderr)
	return set
}

func parse(set *flag.FlagSet, args []string, required map[string]*string) error {
	if set.Parse(args) != nil || set.NArg() != 0 {
		return errUsage
	}
	for name, value := range required {
		if *value == "" {
			return fmt.Errorf("%w: --%s is required", errUsage, name)
		}
	}
	return nil
}

func keygen(args []string, stdout, stderr io.Writer) error {
	set := flags("keygen", stderr)
	keyID := set.String("key-id", "", "identifier the Portal will know the public key by")
	privatePath := set.String("private-key", "", "file to create for the private key (mode 0600, never overwritten)")
	if err := parse(set, args, map[string]*string{"key-id": keyID, "private-key": privatePath}); err != nil {
		return err
	}
	if !keyIDPattern.MatchString(*keyID) {
		return fmt.Errorf("%w: --key-id must be 1-128 lowercase letters, digits, dots, underscores or hyphens, starting with a letter or digit", errUsage)
	}
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return err
	}
	if err := createExclusive(*privatePath, 0o600, []byte(encode(private.Seed())+"\n")); err != nil {
		return err
	}
	fingerprint := sha256.Sum256(public)
	object, _ := json.MarshalIndent(struct {
		ID          string  `json:"id"`
		PublicKey   string  `json:"public_key"`
		NotBeforeMS string  `json:"not_before_ms"`
		NotAfterMS  *string `json:"not_after_ms"`
	}{*keyID, encode(public), "0", nil}, "", "  ")
	fmt.Fprintf(stdout, "Key ID:      %s\nPublic key:  %s\nSHA-256:     %s (of the raw 32-byte public key; compare it through an independent channel)\nPrivate key: %s (mode 0600). Keep it secret and back it up; never enroll or paste it.\n\n", *keyID, encode(public), hex.EncodeToString(fingerprint[:]), *privatePath)
	fmt.Fprintf(stdout, "Key object for the administrator's \"register\" or \"add_key\" request in the Portal (Manage, Publishers):\n%s\n", object)
	return nil
}

func sign(args []string, stdout, stderr io.Writer) error {
	set := flags("sign", stderr)
	descriptorPath := set.String("descriptor", "", "the exact descriptor.json bytes to sign")
	privatePath := set.String("private-key", "", "private key file from keygen")
	keyID := set.String("key-id", "", "identifier the public key is enrolled under")
	out := set.String("out", "", "signature file to create (never overwritten)")
	if err := parse(set, args, map[string]*string{"descriptor": descriptorPath, "private-key": privatePath, "key-id": keyID, "out": out}); err != nil {
		return err
	}
	if !keyIDPattern.MatchString(*keyID) {
		return fmt.Errorf("%w: --key-id must be 1-128 lowercase letters, digits, dots, underscores or hyphens, starting with a letter or digit", errUsage)
	}
	raw, err := readBounded(*descriptorPath, maxDescriptorBytes)
	if err != nil {
		return err
	}
	publisher, err := checkDescriptor(raw)
	if err != nil {
		return err
	}
	private, err := readPrivateKey(*privatePath)
	if err != nil {
		return err
	}
	digest := sha256.Sum256(raw)
	envelope, err := json.Marshal(envelope{
		Format: envelopeFormat, Algorithm: "Ed25519", Publisher: publisher, KeyID: *keyID,
		DescriptorSHA256: hex.EncodeToString(digest[:]), Signature: encode(ed25519.Sign(private, frame(raw))),
	})
	if err != nil {
		return err
	}
	if err := createExclusive(*out, 0o644, envelope); err != nil {
		return err
	}
	fmt.Fprintf(stdout, "signed publisher=%s key_id=%s descriptor_sha256=%s -> %s\n", publisher, *keyID, hex.EncodeToString(digest[:]), *out)
	return nil
}

func verify(args []string, stdout, stderr io.Writer) error {
	set := flags("verify", stderr)
	descriptorPath := set.String("descriptor", "", "the exact descriptor.json bytes")
	signaturePath := set.String("signature", "", "the descriptor.sig file")
	publicKey := set.String("public-key", "", "public key, 43 characters of unpadded base64url")
	keyID := set.String("key-id", "", "optional: require this key ID in the signature")
	if err := parse(set, args, map[string]*string{"descriptor": descriptorPath, "signature": signaturePath, "public-key": publicKey}); err != nil {
		return err
	}
	public, ok := decode(*publicKey, ed25519.PublicKeySize)
	if !ok {
		return fmt.Errorf("%w: --public-key must be 43 characters of canonical unpadded base64url", errUsage)
	}
	raw, err := readBounded(*descriptorPath, maxDescriptorBytes)
	if err != nil {
		return err
	}
	rawEnvelope, err := readBounded(*signaturePath, maxEnvelopeBytes)
	if err != nil {
		return err
	}
	detached, err := parseEnvelope(rawEnvelope)
	if err != nil {
		return err
	}
	publisher, err := checkDescriptor(raw)
	if err != nil {
		return err
	}
	digest := sha256.Sum256(raw)
	if detached.Publisher != publisher {
		return errors.New("signature names a different publisher than the descriptor")
	}
	if detached.DescriptorSHA256 != hex.EncodeToString(digest[:]) {
		return errors.New("signature is for different descriptor bytes")
	}
	if *keyID != "" && detached.KeyID != *keyID {
		return fmt.Errorf("signature names key %q, not %q", detached.KeyID, *keyID)
	}
	signature, _ := decode(detached.Signature, ed25519.SignatureSize)
	if !ed25519.Verify(ed25519.PublicKey(public), frame(raw), signature) {
		return errors.New("signature does not verify with this public key")
	}
	fmt.Fprintf(stdout, "ok publisher=%s key_id=%s descriptor_sha256=%s\n", publisher, detached.KeyID, detached.DescriptorSHA256)
	return nil
}

type envelope struct {
	Format           string `json:"format"`
	Algorithm        string `json:"algorithm"`
	Publisher        string `json:"publisher"`
	KeyID            string `json:"key_id"`
	DescriptorSHA256 string `json:"descriptor_sha256"`
	Signature        string `json:"signature"`
}

func frame(raw []byte) []byte {
	framed := make([]byte, len(frameDomain)+8+len(raw))
	copy(framed, frameDomain)
	binary.BigEndian.PutUint64(framed[len(frameDomain):], uint64(len(raw)))
	copy(framed[len(frameDomain)+8:], raw)
	return framed
}

func encode(data []byte) string { return base64.RawURLEncoding.EncodeToString(data) }

// decode accepts only the canonical unpadded base64url encoding of exactly size bytes.
func decode(value string, size int) ([]byte, bool) {
	decoded, err := base64.RawURLEncoding.Strict().DecodeString(value)
	return decoded, err == nil && len(decoded) == size && encode(decoded) == value
}

// parseEnvelope reads the closed detached envelope: exactly the six lowercase string fields, no
// duplicate (including escaped) or unknown key, nothing after the object.
func parseEnvelope(raw []byte) (envelope, error) {
	var zero envelope
	bad := errors.New("signature file is not a valid portal.app.signature/1-dev.1 envelope")
	if !utf8.Valid(raw) {
		return zero, bad
	}
	fields := map[string]string{}
	d := json.NewDecoder(bytes.NewReader(raw))
	if token, err := d.Token(); err != nil || token != json.Delim('{') {
		return zero, bad
	}
	for d.More() {
		name, err := d.Token()
		key, isString := name.(string)
		if err != nil || !isString {
			return zero, bad
		}
		var value any
		if d.Decode(&value) != nil {
			return zero, bad
		}
		text, isText := value.(string)
		if _, duplicate := fields[key]; duplicate || !isText {
			return zero, bad
		}
		fields[key] = text
	}
	if token, err := d.Token(); err != nil || token != json.Delim('}') {
		return zero, bad
	}
	if _, err := d.Token(); err != io.EOF {
		return zero, bad
	}
	if len(fields) != 6 {
		return zero, bad
	}
	value := envelope{fields["format"], fields["algorithm"], fields["publisher"], fields["key_id"], fields["descriptor_sha256"], fields["signature"]}
	_, signatureOK := decode(value.Signature, ed25519.SignatureSize)
	if value.Format != envelopeFormat || value.Algorithm != "Ed25519" || !publisherPattern.MatchString(value.Publisher) ||
		!keyIDPattern.MatchString(value.KeyID) || !digestPattern.MatchString(value.DescriptorSHA256) || !signatureOK {
		return zero, bad
	}
	return value, nil
}

// checkDescriptor applies the checks a signature depends on and returns the publisher: UTF-8 JSON
// object without duplicate keys at any depth, nothing after it, format portal.app/v2, and a valid
// publisher slug. The signed bytes stay exactly as given. Full descriptor validation belongs to the
// build and pack steps and to the Portal.
func checkDescriptor(raw []byte) (string, error) {
	bad := errors.New("descriptor is not a strict portal.app/v2 JSON object")
	if !utf8.Valid(raw) {
		return "", bad
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if token, err := d.Token(); err != nil || token != json.Delim('{') || !scanObject(d, 0) {
		return "", bad
	}
	if _, err := d.Token(); err != io.EOF {
		return "", bad
	}
	var head struct {
		Format    string `json:"format"`
		Publisher string `json:"publisher"`
	}
	var top map[string]json.RawMessage
	if json.Unmarshal(raw, &top) != nil {
		return "", bad
	}
	for key := range top {
		// encoding/json matches field names without regard to case; Portal does not, so a
		// "Publisher" beside "publisher" must not decide what the envelope names.
		if lower := strings.ToLower(key); (lower == "format" || lower == "publisher") && key != lower {
			return "", bad
		}
	}
	if json.Unmarshal(raw, &head) != nil || head.Format != descriptorFormat {
		return "", errors.New("descriptor format is not " + descriptorFormat)
	}
	if !publisherPattern.MatchString(head.Publisher) {
		return "", errors.New("descriptor publisher is missing or not a valid publisher ID")
	}
	return head.Publisher, nil
}

// scanObject consumes an object whose opening brace was read, refusing duplicate keys.
func scanObject(d *json.Decoder, depth int) bool {
	if depth > 64 {
		return false
	}
	seen := map[string]bool{}
	for d.More() {
		name, err := d.Token()
		key, ok := name.(string)
		if err != nil || !ok || seen[key] {
			return false
		}
		seen[key] = true
		if !scanValue(d, depth+1) {
			return false
		}
	}
	token, err := d.Token()
	return err == nil && token == json.Delim('}')
}

func scanValue(d *json.Decoder, depth int) bool {
	token, err := d.Token()
	if err != nil {
		return false
	}
	switch token {
	case json.Delim('{'):
		return scanObject(d, depth)
	case json.Delim('['):
		if depth > 64 {
			return false
		}
		for d.More() {
			if !scanValue(d, depth+1) {
				return false
			}
		}
		end, err := d.Token()
		return err == nil && end == json.Delim(']')
	}
	return true
}

func readBounded(path string, limit int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is not a regular file", path)
	}
	raw, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > limit {
		return nil, fmt.Errorf("%s is larger than %d bytes", path, limit)
	}
	return raw, nil
}

// readPrivateKey reads the seed written by keygen and refuses a file other users can read.
func readPrivateKey(path string) (ed25519.PrivateKey, error) {
	// The key file itself must be what is checked: a symbolic link would let whoever controls
	// the link's directory swap in another 0600 file.
	if link, err := os.Lstat(path); err != nil {
		return nil, err
	} else if link.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("%s is a symbolic link; point --private-key at the key file itself", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if link, err := os.Lstat(path); err != nil || !os.SameFile(link, info) {
		return nil, fmt.Errorf("%s changed while it was opened", path)
	}
	if !info.Mode().IsRegular() {
		return nil, fmt.Errorf("%s is not a regular file", path)
	}
	if info.Mode().Perm()&0o077 != 0 {
		return nil, fmt.Errorf("%s has permissions %04o; a private key must not be accessible to group or others (chmod 600)", path, info.Mode().Perm())
	}
	raw, err := io.ReadAll(io.LimitReader(file, maxKeyFileBytes+1))
	if err != nil {
		return nil, err
	}
	seed, ok := decode(string(bytes.TrimSpace(raw)), ed25519.SeedSize)
	if len(raw) > maxKeyFileBytes || !ok {
		return nil, fmt.Errorf("%s is not a private key written by keygen", path)
	}
	return ed25519.NewKeyFromSeed(seed), nil
}

// createExclusive creates path with mode and content, never replacing or following anything there.
func createExclusive(path string, mode os.FileMode, content []byte) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		if errors.Is(err, os.ErrExist) {
			return fmt.Errorf("%s already exists; it is never overwritten", path)
		}
		return err
	}
	_, err = file.Write(content)
	if err == nil {
		err = file.Sync()
	}
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		os.Remove(path)
	}
	return err
}
