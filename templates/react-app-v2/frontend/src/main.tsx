import { createRoot } from "react-dom/client";
import { AppRoot } from "@portal-app/sdk/root-v2";
import { Application } from "./App";
import bootstrap from "./bootstrap.json";

createRoot(document.getElementById("app")!).render(
  <AppRoot parentOrigin={bootstrap.parentOrigin}>
    <Application />
  </AppRoot>,
);
