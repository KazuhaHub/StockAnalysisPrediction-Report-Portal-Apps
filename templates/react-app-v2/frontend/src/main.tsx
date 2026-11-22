import { createRoot } from "react-dom/client";
import { AppRoot } from "@portal-app/sdk/root-v2";
import { Application } from "./App";

createRoot(document.getElementById("app")!).render(
  <AppRoot>
    <Application />
  </AppRoot>,
);
