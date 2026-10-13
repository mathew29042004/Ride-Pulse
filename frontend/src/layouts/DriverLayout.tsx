import { FileCheck, IndianRupee, Navigation, User } from "lucide-react";
import { Link, Outlet } from "react-router";

import { FrameAside, PhoneFrame } from "@/components/PhoneFrame";

import { AppTabs } from "./AppTabs";

const TABS = [
  { to: "/drive", label: "Drive", icon: Navigation, end: true },
  { to: "/drive/earnings", label: "Earnings", icon: IndianRupee },
  { to: "/drive/documents", label: "Documents", icon: FileCheck },
  { to: "/drive/account", label: "Account", icon: User },
];

export default function DriverLayout() {
  return (
    <PhoneFrame
      aside={
        <FrameAside title="Driver app">
          <p>Go online to start receiving trip offers. Each offer shows the pickup distance, the trip and your estimated earnings, with 20 seconds to accept.</p>
          <p>
            <strong className="text-fg">Demo tip:</strong> tap anywhere on the map to move your car (a stand-in for GPS). Then open the{" "}
            <Link to="/ride" target="_blank" className="font-semibold text-brand-strong underline">
              rider app
            </Link>{" "}
            in another window and book a ride nearby.
          </p>
          <p>Cash trips leave platform commission as dues in your wallet. Drivers over the dues limit can't go online until they pay.</p>
        </FrameAside>
      }
    >
      <div className="relative flex min-h-0 flex-1 flex-col md:pt-11">
        <Outlet />
      </div>
      <AppTabs tabs={TABS} />
    </PhoneFrame>
  );
}
