import { Briefcase, Snowflake, UserRound, VolumeX } from "lucide-react";

export type RidePreference = "QUIET" | "AC" | "LUGGAGE" | "WOMAN_DRIVER";

/** Ride preferences, in the order shown. AC and luggage are for cars only. */
export const PREFERENCES: { value: RidePreference; label: string; driverLabel: string; icon: typeof VolumeX; carsOnly?: boolean }[] = [
  { value: "QUIET", label: "Quiet ride", driverLabel: "Prefers a quiet ride", icon: VolumeX },
  { value: "AC", label: "AC on", driverLabel: "AC on, please", icon: Snowflake, carsOnly: true },
  { value: "LUGGAGE", label: "Extra luggage", driverLabel: "Has extra luggage", icon: Briefcase, carsOnly: true },
  { value: "WOMAN_DRIVER", label: "Woman driver", driverLabel: "Woman driver preferred", icon: UserRound },
];

export const isCar = (rideType: string) => !["BIKE", "AUTO"].includes(rideType);
