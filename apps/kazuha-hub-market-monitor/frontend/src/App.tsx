import { useAppNavigation, useAppSurface } from "@portal-app/sdk/root-v2";
import { AdminPage } from "./pages/Admin";
import { EtfPage } from "./pages/Etf";
import { MarginPage } from "./pages/Margin";
import { OverviewPage } from "./pages/Overview";
import { PanoramaPage } from "./pages/Panorama";
import { QuantPage } from "./pages/Quant";
import { SentimentPage } from "./pages/Sentiment";
import "./style.css";

export function Application() {
  const navigation = useAppNavigation();
  // The admin view is the same bundle launched on the admin surface; its only
  // route is /admin, so the surface alone picks the page.
  if (useAppSurface() === "admin") return <AdminPage />;
  switch (navigation.path) {
    case "/margin":
      return <MarginPage />;
    case "/sentiment":
      return <SentimentPage />;
    case "/etf":
      return <EtfPage />;
    case "/panorama":
      return <PanoramaPage />;
    case "/quant":
      return <QuantPage />;
    default:
      return <OverviewPage />;
  }
}
