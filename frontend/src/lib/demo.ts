/** Demo accounts created by `python manage.py seed_demo` (see README). */
export const DEMO_PASSWORD = "RidePulse@2026";

export const DEMO_ACCOUNTS = [
  { label: "Rider", email: "rider@ridepulse.dev", description: "Book rides in Chennai, track your driver live, pay and rate." },
  { label: "Driver", email: "driver@ridepulse.dev", description: "Go online, accept trip offers, start with the ride PIN, see earnings." },
  { label: "Operations", email: "ops@ridepulse.dev", description: "Live map, dispatch, surge pricing, driver verification, analytics." },
  { label: "Support", email: "support@ridepulse.dev", description: "Ticket queue, refunds and the SOS safety desk." },
  { label: "Admin", email: "admin@ridepulse.dev", description: "Everything, including the audit trail and staff accounts." },
] as const;
