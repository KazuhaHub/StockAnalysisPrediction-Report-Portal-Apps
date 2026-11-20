package main

import (
	"encoding/json"
	"os"
	"slices"
	"strings"
	"testing"
)

type descriptor struct {
	ID      string `json:"id"`
	Backend *struct {
		Kind      string   `json:"kind"`
		Protocol  string   `json:"protocol"`
		Platforms []string `json:"platforms"`
		Resources struct {
			MemoryMiB int `json:"memory_mib"`
			CPUMillis int `json:"cpu_millis"`
			PIDs      int `json:"pids"`
		} `json:"resources"`
	} `json:"backend"`
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
	if strings.Contains(string(raw), "PUBLISHER"+"_JSON") {
		t.Skip("template placeholders are not JSON: run this in a generated app")
	}
	var d descriptor
	if err := json.Unmarshal(raw, &d); err != nil {
		t.Fatal(err)
	}
	return d
}

// The descriptor is what an administrator reviews; the service is what runs.
// These checks keep the two from drifting apart.
func TestDescriptorMatchesTheService(t *testing.T) {
	d := readDescriptor(t)
	if d.ID != applicationID {
		t.Fatalf("descriptor id %q, service %q", d.ID, applicationID)
	}
	if d.Backend == nil || d.Backend.Kind != "oci" || d.Backend.Protocol != "portal.backend/1" {
		t.Fatalf("backend %+v", d.Backend)
	}
	if !slices.Contains(d.Backend.Platforms, "linux/amd64") {
		t.Fatalf("platforms %v", d.Backend.Platforms)
	}
	r := d.Backend.Resources
	if r.MemoryMiB < 16 || r.MemoryMiB > 4096 || r.CPUMillis < 25 || r.CPUMillis > 4000 || r.PIDs < 16 || r.PIDs > 1024 {
		t.Fatalf("resources %+v are outside the descriptor bounds", r)
	}
	// The task route checks the tasks.schedule resource, so the app must be able to hold it,
	// and tasks.schedule needs background.run.
	both := append(slices.Clone(d.Capabilities.Required), d.Capabilities.Optional...)
	if !slices.Contains(both, "tasks.schedule") || !slices.Contains(both, "background.run") {
		t.Fatalf("the task route needs tasks.schedule and background.run: %+v", d.Capabilities)
	}
}

func TestForwardProxyDeclarationIsConsistent(t *testing.T) {
	d := readDescriptor(t)
	declared := slices.Contains(d.Capabilities.Optional, "network.proxy")
	// Doc 184: network.proxy is optional only and needs background.run.
	if slices.Contains(d.Capabilities.Required, "network.proxy") {
		t.Fatal("network.proxy must be optional")
	}
	if !declared {
		if d.NetworkProxy != nil {
			t.Fatal("network_proxy hosts without the network.proxy capability")
		}
		return
	}
	both := append(slices.Clone(d.Capabilities.Required), d.Capabilities.Optional...)
	if !slices.Contains(both, "background.run") {
		t.Fatal("network.proxy needs background.run")
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
}
