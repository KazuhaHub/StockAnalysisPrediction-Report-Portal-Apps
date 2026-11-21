// DEVELOPMENT ONLY entry of the sandboxed app frame. The production entry is
// src/main.tsx, whose parent origin is immutable build configuration; here the
// stand-in host is the dev server itself.
import { createRoot } from "react-dom/client";
import { AppRoot } from "@portal-app/sdk/root-v2";
import { Application } from "../src/App";

createRoot(document.getElementById("app")!).render(
  <AppRoot parentOrigin={new URL(import.meta.url).origin}>
    <Application />
  </AppRoot>,
);
