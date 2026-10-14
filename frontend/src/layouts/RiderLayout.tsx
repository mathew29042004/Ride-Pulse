import { Clock, House, User, Wallet } from "lucide-react";
import { Link, Outlet, useLocation } from "react-router";

import { FrameAside, PhoneFrame } from "@/components/PhoneFrame";

const TABS = [
  { to: "/ride", label: "Ride", icon: House, end: true },
  { to: "/ride/activity", label: "Activity", icon: Clock },
  { to: "/ride/wallet", label: "Wallet", icon: Wallet },
  { to: "/ride/account", label: "Account", icon: User },
];

export default function RiderLayout() {
  const { pathname } = useLocation();
  const immersive = pathname.startsWith("/ride/book") || pathname.startsWith("/ride/trips/");
  const mapScreen = immersive || pathname === "/ride" || pathname === "/ride/";
  return (
    <PhoneFrame
      title="Rider"
      tabs={TABS}
      hideTabs={immersive}
      mapScreen={mapScreen}
      aside={
        <FrameAside title="Rider app">
          <p>Book a ride the way you would on a phone: pick a destination, compare upfront fares for each ride type, and track your driver live.</p>
          <p>
            <strong className="text-fg">Try it end to end:</strong> open the{" "}
            <Link to="/drive" target="_blank" className="font-semibold text-brand-strong underline">
              driver app
            </Link>{" "}
            in another window (log in as the demo driver), go online near your pickup and accept your own ride. Or keep the
            simulator running and a bot driver will pick you up.
          </p>
          <p>The ride PIN is shown only to you. The driver can't start the trip without it.</p>
        </FrameAside>
      }
    >
      <Outlet />
    </PhoneFrame>
  );
}
