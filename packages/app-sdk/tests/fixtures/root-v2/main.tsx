// Development build fixture only; it is not an installable catalogue application.
import { createRoot } from "react-dom/client";
import { Button } from "antd";
import { AppRoot, useAppPresentation } from "@portal-app/sdk/root-v2";
function Fixture() {
  const { presentation } = useAppPresentation();
  return (
    <Button>
      {presentation.locale} / {presentation.timeZone}
    </Button>
  );
}
// Production bootstrap must bind this to an independently trusted Portal origin.
createRoot(document.getElementById("app")!).render(
  <AppRoot parentOrigin="https://portal.example.invalid">
    <Fixture />
  </AppRoot>,
);
