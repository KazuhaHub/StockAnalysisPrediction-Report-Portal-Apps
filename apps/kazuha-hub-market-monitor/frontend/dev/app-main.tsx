// DEVELOPMENT ONLY entry of the sandboxed app frame. The production entry is
// src/main.tsx; the bridge client derives the parent origin from the document
// URL, which here is the dev server itself (the stand-in host).
import { createRoot } from "react-dom/client";
import { AppRoot } from "@portal-app/sdk/root-v2";
import { Application } from "../src/App";

createRoot(document.getElementById("app")!).render(
  <AppRoot>
    <Application />
  </AppRoot>,
);
