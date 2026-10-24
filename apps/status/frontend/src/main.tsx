import { createRoot } from "react-dom/client";
import { PortalClient } from "@portal-app/sdk";
import { StatusApp } from "./App";
import "./private.css";

const client = new PortalClient("status");
createRoot(document.getElementById("app")!).render(
  <StatusApp client={client} />,
);
