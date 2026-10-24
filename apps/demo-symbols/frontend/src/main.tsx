import { createRoot } from "react-dom/client";
import { PortalClient } from "@portal-app/sdk";
import { Demo } from "./App";
const client = new PortalClient("demo-symbols");
createRoot(document.getElementById("app")!).render(<Demo client={client} />);
