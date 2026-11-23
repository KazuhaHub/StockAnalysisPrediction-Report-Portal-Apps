package main

import (
	"encoding/json"
	"os"
	"slices"
	"strconv"
	"strings"
	"testing"
)

type descriptor struct {
	Capabilities struct {
		Required []string `json:"required"`
		Optional []string `json:"optional"`
	} `json:"capabilities"`
	NetworkProxy *struct {
		Hosts []string `json:"hosts"`
	} `json:"network_proxy"`
}

func readDescriptor(t *testing.T) descriptor {
	t.Helper()
	raw, err := os.ReadFile("../app.v2.json")
	if err != nil {
		t.Fatal(err)
	}
	var d descriptor
	if err := json.Unmarshal(raw, &d); err != nil {
		t.Fatal(err)
	}
	return d
}

func TestDescriptorDeclaresTheForwardProxy(t *testing.T) {
	d := readDescriptor(t)
	// Doc 184: network.proxy is optional only and needs background.run.
	if !slices.Contains(d.Capabilities.Optional, "network.proxy") || slices.Contains(d.Capabilities.Required, "network.proxy") {
		t.Fatalf("capabilities %+v", d.Capabilities)
	}
	if !slices.Contains(d.Capabilities.Required, "background.run") {
		t.Fatalf("background.run is not declared: %+v", d.Capabilities)
	}
	if d.NetworkProxy == nil || len(d.NetworkProxy.Hosts) == 0 || len(d.NetworkProxy.Hosts) > 64 {
		t.Fatalf("network_proxy %+v", d.NetworkProxy)
	}
	hosts := d.NetworkProxy.Hosts
	if !slices.IsSorted(hosts) || len(slices.Compact(slices.Clone(hosts))) != len(hosts) {
		t.Fatalf("hosts are not sorted and unique: %v", hosts)
	}
	for _, h := range hosts {
		base := strings.TrimPrefix(h, "*.")
		if h != strings.ToLower(h) || strings.HasSuffix(h, ".") || strings.Contains(base, "*") || strings.Contains(h, ":") || strings.Count(base, ".") < 1 {
			t.Errorf("host entry %q breaks the entry rules", h)
		}
	}
	// A wildcard matches exactly one label, so *.eastmoney.com does not cover
	// N.push2delay.eastmoney.com: the push2 quote nodes redirect there from
	// production, and the proxy refuses an undeclared redirect target.
	for _, want := range []string{"*.eastmoney.com", "*.push2.eastmoney.com", "1.push2delay.eastmoney.com",
		"82.push2delay.eastmoney.com", "qt.gtimg.cn"} {
		if !slices.Contains(hosts, want) {
			t.Errorf("missing %s", want)
		}
	}
}

// The runner admits the backend only when /health/ready reports the data format the descriptor declares
// (data.schema). A mismatch leaves an install waiting at probe forever, as 0.1.0-beta.1 did on production.
func TestDescriptorDataSchemaMatchesReadiness(t *testing.T) {
	raw, err := os.ReadFile("../app.v2.json")
	if err != nil {
		t.Fatal(err)
	}
	var d struct {
		Data struct {
			Schema          int   `json:"schema"`
			ReadableSchemas []int `json:"readable_schemas"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &d); err != nil {
		t.Fatal(err)
	}
	if got := strconv.Itoa(d.Data.Schema); got != readinessDataFormat {
		t.Fatalf("app.v2.json data.schema is %s, /health/ready reports %s", got, readinessDataFormat)
	}
	if !slices.Contains(d.Data.ReadableSchemas, d.Data.Schema) {
		t.Fatalf("readable_schemas %v does not include schema %d", d.Data.ReadableSchemas, d.Data.Schema)
	}
}
