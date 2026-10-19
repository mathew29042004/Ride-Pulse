import { Accessibility, Baby, Briefcase, Ear, Eye, HandHelping, Leaf, PawPrint, Snowflake, UserRound, VolumeX } from "lucide-react";

export type RidePreference = "QUIET" | "AC" | "LUGGAGE" | "WOMAN_DRIVER" | "ELECTRIC" | "CHILD_SEAT" | "PET";
export type AccessibilityNeed = "WHEELCHAIR" | "ASSIST" | "HEARING" | "LOW_VISION";

/** Ride preferences, in the order shown. AC and luggage are for cars only. */
export const PREFERENCES: { value: RidePreference; label: string; driverLabel: string; icon: typeof VolumeX; carsOnly?: boolean; notOnBikes?: boolean }[] = [
  { value: "QUIET", label: "Quiet ride", driverLabel: "Prefers a quiet ride", icon: VolumeX },
  { value: "AC", label: "AC on", driverLabel: "AC on, please", icon: Snowflake, carsOnly: true },
  { value: "LUGGAGE", label: "Extra luggage", driverLabel: "Has extra luggage", icon: Briefcase, carsOnly: true },
  { value: "WOMAN_DRIVER", label: "Woman driver", driverLabel: "Woman driver preferred", icon: UserRound },
  { value: "ELECTRIC", label: "Electric", driverLabel: "Prefers an electric vehicle", icon: Leaf },
  { value: "CHILD_SEAT", label: "Child seat", driverLabel: "Needs a child seat", icon: Baby, carsOnly: true },
  { value: "PET", label: "Travelling with a pet", driverLabel: "Has a pet with them", icon: PawPrint, notOnBikes: true },
];

export const isCar = (rideType: string) => !["BIKE", "AUTO"].includes(rideType);

/** Accessibility needs, saved in Account and sent with every booking. */
export const ACCESSIBILITY: { value: AccessibilityNeed; label: string; hint: string; driverLabel: string; icon: typeof VolumeX }[] = [
  { value: "WHEELCHAIR", label: "I use a wheelchair", hint: "Only wheelchair-accessible cars are sent (ramp or lift).", driverLabel: "Wheelchair user", icon: Accessibility },
  { value: "ASSIST", label: "Help getting in and out", hint: "Drivers trained in boarding assistance come first.", driverLabel: "Needs help boarding", icon: HandHelping },
  { value: "HEARING", label: "Deaf or hard of hearing", hint: "Drivers are asked to message, not call.", driverLabel: "Deaf / hard of hearing: message, don't call", icon: Ear },
  { value: "LOW_VISION", label: "Blind or low vision", hint: "Drivers are asked to come and find you.", driverLabel: "Blind / low vision: please find the rider", icon: Eye },
];
