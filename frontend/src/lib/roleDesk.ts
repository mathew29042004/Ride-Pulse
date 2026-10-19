/** Each role's desk: the pages that role works in every day, first in the sidebar, and the page
 * they land on after signing in (the first one). Everything else their role allows stays under
 * "More tools". Pages are still gated by capabilities; this only decides what comes first. */

import type { Role } from "./types";

const CHAT = "/ops/chat";
const WORK = "/ops/work";

export const ROLE_DESK: Partial<Record<Role, { title: string; pages: string[] }>> = {
  COMMANDER: { title: "Commander's desk", pages: ["/ops/command", "/ops/live", "/ops/incidents", "/ops/powers", "/ops/team", CHAT] },
  CHIEF_OF_STAFF: { title: "Chief of staff's desk", pages: ["/ops/brief", "/ops/briefing", "/ops/alerts", "/ops", "/ops/live", CHAT] },
  ADMIN: { title: "Admin desk", pages: ["/ops", "/ops/live", "/ops/team", "/ops/audit", "/ops/platform", "/ops/powers", "/ops/security", CHAT] },
  REGIONAL_MANAGER: { title: "Regional desk", pages: ["/ops", "/ops/live", "/ops/pnl", "/ops/team", "/ops/appraisals", WORK, CHAT, "/ops/brief"] },
  OPS_MANAGER: { title: "City operations desk", pages: ["/ops", "/ops/live", "/ops/trips", "/ops/drivers", "/ops/pricing", "/ops/weather", WORK, CHAT, "/ops/brief"] },
  ASSOC_RIDES: { title: "Rides desk", pages: ["/ops", "/ops/trips", "/ops/drivers", "/ops/pricing", WORK, CHAT] },
  ASSOC_SUPPORT: { title: "Support desk", pages: ["/ops/support", "/ops/safety", "/ops/grievances", "/ops/lost-found", WORK, CHAT] },
  ASSOC_MAINTENANCE: { title: "Fleet desk", pages: ["/ops/verification", "/ops/upkeep", "/ops/fleet-owners", "/ops/drivers", WORK, CHAT] },
  ASSOC_INTERCITY: { title: "Intercity desk", pages: ["/ops/tours", "/ops/trips", "/ops/pricing", WORK, CHAT] },
  ASSOC_PARCELS: { title: "Parcels desk", pages: ["/ops/trips", "/ops/support", "/ops/drivers", WORK, CHAT] },
  SUPPORT_LEAD: { title: "Support desk", pages: ["/ops/support", "/ops/safety", "/ops/lost-found", "/ops/grievances", WORK, CHAT] },
  SUPPORT_AGENT: { title: "Support desk", pages: ["/ops/support", "/ops/safety", "/ops/lost-found", WORK, CHAT] },
  FLEET_EXECUTIVE: { title: "Fleet desk", pages: ["/ops/verification", "/ops/drivers", "/ops/upkeep", WORK, CHAT] },
  FINANCE_MANAGER: { title: "Finance desk", pages: ["/ops/powers", "/ops/finance", "/ops/pnl", "/ops/gst", "/ops/tds", CHAT, "/ops/brief"] },
  HR_MANAGER: { title: "People desk", pages: ["/ops/powers", "/ops/payroll", "/ops/team", "/ops/appraisals", "/ops/announcements", CHAT, "/ops/brief"] },
  SAFETY_OFFICER: { title: "Safety desk", pages: ["/ops/safety", "/ops/powers", "/ops/speed", "/ops/fraud", "/ops/support", CHAT, "/ops/brief"] },
  DISPATCH_CONTROLLER: { title: "Dispatch desk", pages: ["/ops/live", "/ops/powers", "/ops/trips", "/ops/drivers", CHAT] },
  COMPLIANCE_OFFICER: { title: "Compliance desk", pages: ["/ops/powers", "/ops/compliance", "/ops/trust", "/ops/audit", "/ops/grievances", CHAT, "/ops/brief"] },
  PRICING_ANALYST: { title: "Pricing desk", pages: ["/ops/pricing", "/ops/promos", "/ops/fuel", "/ops/demand", "/ops/models", CHAT] },
};

/** Every employee's personal pages, at the bottom of their desk. */
export const PERSONAL = ["/ops/approvals", "/ops/company", "/ops/attendance", "/ops/roster", "/ops/payslips", "/ops/expenses"];
