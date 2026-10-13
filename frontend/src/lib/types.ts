export type Role = "ADMIN" | "OPS_MANAGER" | "SUPPORT_AGENT" | "DRIVER" | "RIDER";

export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  role: Role;
  capabilities: string[];
  date_joined: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Point {
  lat: number;
  lng: number;
  address?: string;
}

export interface Place {
  name: string;
  address: string;
  category: string;
  lat: number;
  lng: number;
  city: string;
}

export interface Zone {
  id: number;
  code: string;
  name: string;
  center_lat: number;
  center_lng: number;
  radius_km: number;
  is_airport: boolean;
}

export interface City {
  id: number;
  name: string;
  slug: string;
  state: string;
  center_lat: number;
  center_lng: number;
  radius_km: number;
  zones: Zone[];
}

export interface RideType {
  id: number;
  code: string;
  name: string;
  description: string;
  seats: number;
}

export interface FareLine {
  code: string;
  label: string;
  amount: string;
  kind: "FARE" | "SURGE" | "FEE" | "DISCOUNT" | "TAX";
}

export interface Fare {
  lines: FareLine[];
  surge_multiplier: string;
  ride_fare: string;
  surge_amount: string;
  fees: string;
  discount: string;
  gst: string;
  total: string;
}

export interface EstimateOption {
  ride_type: RideType;
  distance_km: string;
  duration_minutes: string;
  route_polyline: string;
  pickup_eta_min: number | null;
  fare: Fare;
}

export interface Estimate {
  city: string;
  promo_error: string;
  options: EstimateOption[];
}

export type TripStatus =
  | "REQUESTED"
  | "DRIVER_ASSIGNED"
  | "DRIVER_ARRIVED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "CANCELLED"
  | "NO_DRIVER_FOUND";

export type PaymentMethod = "CASH" | "UPI" | "CARD" | "WALLET";

export interface TripParty {
  id: number;
  name: string;
  rating: string;
  /** Staff only: riders and drivers call through the masked bridge. */
  phone: string | null;
}

export interface Trip {
  id: number;
  trip_number: string;
  status: TripStatus;
  status_label: string;
  ride_type: string;
  ride_type_name: string;
  city: string;
  pickup_lat: number;
  pickup_lng: number;
  pickup_address: string;
  dropoff_lat: number;
  dropoff_lng: number;
  dropoff_address: string;
  stop: { lat: number; lng: number; address: string } | null;
  car_confirmed_at: string | null;
  rider: TripParty;
  driver: TripParty | null;
  driver_location: { lat: number; lng: number; heading: number | null } | null;
  vehicle: string | null;
  otp: string | null;
  payment_method: PaymentMethod;
  promo_code: string | null;
  estimated_distance_km: string;
  estimated_duration_min: string;
  surge_multiplier: string;
  estimated_fare: string;
  route_polyline: string;
  route_source: "google" | "estimate";
  pickup_eta_min: string | null;
  requested_at: string;
  assigned_at: string | null;
  arrived_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancelled_by: string;
  cancellation_reason: string;
  cancellation_fee: string;
  actual_distance_km: string | null;
  actual_duration_min: string | null;
  waiting_minutes: string | null;
  pricing_mode: string;
  fare: Fare;
  fare_total: string | null;
  driver_earning: string | null;
  tip_amount: string;
  payment_status: string;
  flags: string[];
  has_rated: boolean;
}

export interface TripEvent {
  id: number;
  kind: string;
  from_status: string;
  to_status: string;
  actor: string | null;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface TripOffer {
  id: number;
  driver: string;
  status: string;
  offered_at: string;
  expires_at: string;
  responded_at: string | null;
  distance_km: number;
  eta_minutes: number;
  rank_score: number;
  dispatch_mode: string;
}

export interface Offer {
  offer_id: number;
  trip_id: number;
  trip_number: string;
  ride_type: string;
  pickup: Point;
  dropoff: Point;
  pickup_distance_km: number;
  pickup_eta_min: number;
  trip_distance_km: string;
  estimated_earning: string;
  surge: string;
  payment_method: PaymentMethod;
  expires_at: string;
}

export interface Vehicle {
  id: number;
  ride_type: string;
  make: string;
  model: string;
  registration_number: string;
  registration_display: string;
  year: number;
  color: string;
  seats: number;
  is_active: boolean;
}

export interface DriverDocument {
  id: number;
  driver: number;
  driver_name: string;
  doc_type: string;
  number_last4: string;
  file: string | null;
  expires_on: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "SUPERSEDED";
  rejection_reason: string;
  reviewed_at: string | null;
  created_at: string;
}

export interface Driver {
  id: number;
  name: string;
  email: string;
  phone: string;
  city: string;
  license_number: string;
  license_expiry: string;
  onboarding_status: string;
  availability: "OFFLINE" | "ONLINE" | "ON_TRIP";
  current_lat: number | null;
  current_lng: number | null;
  location_updated_at: string | null;
  rating: string;
  rating_count: number;
  acceptance_rate: string;
  completed_trips: number;
  cancelled_trips: number;
  safety_score: number | null;
  approved_at: string | null;
  suspended_reason: string;
  vehicle: Vehicle | null;
  wallet_balance: string;
  missing_documents: string[];
  compliance_problems: string[];
}

export interface Rider {
  id: number;
  name: string;
  email: string;
  phone: string;
  rating: string;
  rating_count: number;
  completed_trips: number;
  referral_code: string;
  default_payment_method: PaymentMethod;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  is_blocked: boolean;
  blocked_reason: string;
  wallet_balance: string;
  /** Only on the rider's own profile. */
  referrals?: { joined: number; rewarded: number; bonus: string; earned: string };
  created_at: string;
}

export interface SavedPlace {
  id: number;
  label: "HOME" | "WORK" | "OTHER";
  name: string;
  address: string;
  lat: number;
  lng: number;
}

export interface StatementEntry {
  id: number;
  reference: string;
  kind: string;
  kind_label: string;
  description: string;
  trip_id: number | null;
  amount: string;
  created_at: string;
}

export interface Wallet {
  balance: string;
  statement: StatementEntry[];
}

export interface Payout {
  id: number;
  payout_number: string;
  driver: number;
  driver_name: string;
  amount: string;
  period_start: string;
  period_end: string;
  status: "PENDING" | "PAID" | "FAILED";
  bank_reference: string;
  failure_reason: string;
  paid_at: string | null;
  created_at: string;
}

export interface Earnings {
  period: string;
  trips: number;
  fares: string;
  earnings: string;
  trip_earnings: string;
  tips: string;
  cancellation_fees: string;
  commission: string;
  cash_collected: string;
  distance_km: string;
  daily: { date: string; earnings: string; trips: number }[];
}

export interface TicketMessage {
  id: number;
  author: string;
  author_is_staff: boolean;
  body: string;
  is_internal: boolean;
  created_at: string;
}

export interface Ticket {
  id: number;
  ticket_number: string;
  raised_by: string;
  trip: number | null;
  trip_number: string | null;
  category: string;
  priority: "URGENT" | "HIGH" | "NORMAL" | "LOW";
  status: string;
  subject: string;
  description: string;
  assigned_to: string | null;
  sla_due_at: string;
  escalated: boolean;
  resolved_at: string | null;
  resolution: string;
  refund_amount: string;
  created_at: string;
  messages: TicketMessage[];
}

export interface Incident {
  id: number;
  incident_number: string;
  trip: number;
  trip_number: string;
  raised_by: string;
  lat: number | null;
  lng: number | null;
  note: string;
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution_note: string;
  ticket: number | null;
  created_at: string;
}

export interface Notification {
  id: number;
  title: string;
  body: string;
  level: "INFO" | "SUCCESS" | "WARNING" | "DANGER";
  link: string;
  is_read: boolean;
  created_at: string;
}

export interface FareRule {
  id: number;
  city: string;
  ride_type: string;
  base_fare: string;
  per_km: string;
  per_minute: string;
  minimum_fare: string;
  booking_fee: string;
  cancellation_fee: string;
  free_wait_minutes: number;
  wait_per_minute: string;
  airport_fee: string;
  is_active: boolean;
}

export interface SurgeZone {
  zone_id: number;
  zone: string;
  lat: number;
  lng: number;
  multiplier: string;
  demand: number;
  supply: number;
  computed_at: string | null;
}

export interface SurgeOverride {
  id: number;
  zone: number;
  multiplier: string;
  starts_at: string;
  ends_at: string;
  reason: string;
  created_at: string;
}

export interface Promo {
  id: number;
  code: string;
  description: string;
  discount_type: "PERCENT" | "FLAT";
  value: string;
  max_discount: string | null;
  min_fare: string;
  valid_from: string;
  valid_until: string;
  max_redemptions: number | null;
  max_per_rider: number;
  first_ride_only: boolean;
  city: number | null;
  ride_types: string[];
  is_active: boolean;
  usage: { redemptions: number; riders: number; discount_given: string };
}

export interface AuditEntry {
  id: number;
  created_at: string;
  actor: number | null;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  entity_label: string;
  message: string;
  changes: Record<string, [unknown, unknown]>;
  ip_address: string | null;
  request_id: string;
}

export interface LiveDriver {
  id: number;
  name: string;
  lat: number;
  lng: number;
  heading: number | null;
  availability: "ONLINE" | "ON_TRIP";
  ride_type: string | null;
}

export interface LiveTrip {
  id: number;
  trip_number: string;
  status: TripStatus;
  ride_type: string;
  pickup: [number, number];
  dropoff: [number, number];
  driver_id: number | null;
  requested_at: string;
}

export interface Overview {
  days: number;
  kpis: {
    requested: number;
    completed: number;
    completion_rate: number | null;
    cancelled_by_rider: number;
    cancelled_other: number;
    no_driver_found: number;
    gmv: string;
    net_revenue: string;
    commission: string;
    driver_earnings: string;
    discounts: string;
    tips: string;
    avg_fare: string | null;
    avg_distance_km: string | null;
    avg_surge: string | null;
    avg_wait_min: number | null;
    avg_pickup_min: number | null;
  };
  live: {
    drivers_online: number;
    drivers_on_trip: number;
    utilisation: number | null;
    active_trips: number;
    searching: number;
    open_sos: number;
    open_tickets: number;
  };
  driver_hours_online: number;
}

export interface SeriesPoint {
  bucket: string;
  requested: number;
  completed: number;
  lost: number;
  gmv: string;
  avg_surge: number;
}

export interface Breakdown {
  zones: {
    zone: string;
    city: string;
    requests: number;
    completed: number;
    fulfilment: number | null;
    avg_surge: number;
    gmv: string;
    avg_wait_min: number | null;
  }[];
  ride_types: { code: string; name: string; trips: number; gmv: string; avg_fare: string | null }[];
  hourly: { hour: number; requests: number }[];
  heatmap: { cell: string; lat: number; lng: number; requests: number }[];
  leaderboard: {
    driver_id: number;
    name: string;
    trips: number;
    earnings: string;
    rating: string;
    safety_score: number | null;
  }[];
}

export interface ScheduledRide {
  id: number;
  ride_type: string;
  ride_type_name: string;
  pickup: { lat: number; lng: number; address: string };
  dropoff: { lat: number; lng: number; address: string };
  payment_method: PaymentMethod;
  promo_code: string;
  scheduled_for: string;
  quoted_fare: string;
  status: "SCHEDULED" | "DISPATCHED" | "CANCELLED" | "FAILED";
  status_label: string;
  trip_id: number | null;
  failure_reason: string;
  created_at: string;
}
