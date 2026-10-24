import { createRoot } from "react-dom/client";
import { PortalClient } from "@portal-app/sdk";
import { StatusApp } from "./App";
import "./private.css";

const client = new PortalClient("status");
window.addEventListener("pagehide", () => client.dispose(), { once: true });
createRoot(document.getElementById("app")!).render(
  <StatusApp client={client} />,
);
