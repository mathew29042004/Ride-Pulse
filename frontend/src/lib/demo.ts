/** Demo accounts created by `python manage.py seed_demo` (see README). */
export const DEMO_PASSWORD = "RidePulse@2026";

export const DEMO_ACCOUNTS = [
  { label: "Rider", email: "rider@ridepulse.dev", description: "Book rides in Chennai, track your driver live, pay and rate." },
  { label: "Driver", email: "driver@ridepulse.dev", description: "Go online, accept trip offers, start with the ride PIN, see earnings." },
  { label: "Operations", email: "ops@ridepulse.dev", description: "Live map, dispatch, surge pricing, driver verification, analytics." },
  { label: "Support", email: "support@ridepulse.dev", description: "Ticket queue, refunds and the SOS safety desk." },
  { label: "Business", email: "business@ridepulse.dev", description: "Acme Technologies' travel admin: spend dashboard, travel policy, GST invoice, webhooks." },
  { label: "Fleet owner", email: "owner@ridepulse.dev", description: "Your drivers and cars: trips, your share of earnings, vehicle upkeep, payouts." },
  { label: "Admin", email: "admin@ridepulse.dev", description: "Everything, including the audit trail and staff accounts." },
  { label: "Commander", email: "commander@ridepulse.dev", description: "Top of the organisation: the command centre, orders across every city, broadcasts, every team channel." },
  { label: "Chief of staff", email: "chiefofstaff@ridepulse.dev", description: "Keeps the commander updated: briefings, escalations and decisions for the chief, live." },
  { label: "Finance", email: "finance@ridepulse.dev", description: "Approve refunds above ₹2,000, payouts, P&L and GST." },
  { label: "HR", email: "hr@ridepulse.dev", description: "Payroll, transfers and promotions across the organisation." },
  { label: "Safety officer", email: "safety@ridepulse.dev", description: "SOS desk and permanent bans (phone and licence)." },
  { label: "Dispatch", email: "dispatch@ridepulse.dev", description: "Live trips: hand a waiting trip to the driver you choose." },
  { label: "Compliance", email: "compliance@ridepulse.dev", description: "Data requests, audit trail and legal holds." },
  { label: "Pricing", email: "pricing@ridepulse.dev", description: "Fares, surge, promotions and pricing experiments." },
] as const;
