import { useAppNavigation } from "@portal-app/sdk/root-v2";
import { EtfPage } from "./pages/Etf";
import { MarginPage } from "./pages/Margin";
import { OverviewPage } from "./pages/Overview";
import { PanoramaPage } from "./pages/Panorama";
import { SentimentPage } from "./pages/Sentiment";
import "./style.css";

export function Application() {
  const navigation = useAppNavigation();
  switch (navigation.path) {
    case "/margin":
      return <MarginPage />;
    case "/sentiment":
      return <SentimentPage />;
    case "/etf":
      return <EtfPage />;
    case "/panorama":
      return <PanoramaPage />;
    default:
      return <OverviewPage />;
  }
}
