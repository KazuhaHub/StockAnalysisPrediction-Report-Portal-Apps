import { createRoot } from "react-dom/client";
import { PortalClient } from "@portal-app/sdk";
import { Demo } from "./App";
const client = new PortalClient("demo-symbols");
window.addEventListener("pagehide", () => client.dispose(), { once: true });
createRoot(document.getElementById("app")!).render(<Demo client={client} />);
