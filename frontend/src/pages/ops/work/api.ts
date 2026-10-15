/** Types and helpers shared by the manager workspace pages. */

export interface TaskComment {
  id: number;
  kind: "COMMENT" | "STATUS_REQUEST" | "UPDATE" | "SYSTEM";
  body: string;
  author: number | null;
  author_name: string;
  created_at: string;
}

export interface WorkTask {
  id: number;
  number: string;
  title: string;
  description: string;
  assignee: number;
  assignee_name: string;
  assigned_by: number;
  assigned_by_name: string;
  priority: "LOW" | "NORMAL" | "HIGH" | "URGENT";
  priority_label: string;
  status: "TODO" | "IN_PROGRESS" | "DONE" | "CANCELLED";
  status_label: string;
  due_at: string;
  target: number | null;
  progress: number;
  batch: string;
  meeting: number | null;
  meeting_title: string | null;
  started_at: string | null;
  completed_at: string | null;
  is_overdue: boolean;
  awaiting_update: boolean;
  mine: boolean;
  created_at: string;
  comments?: TaskComment[];
}

export interface Attendee {
  user: number;
  name: string;
  response: "INVITED" | "ACCEPTED" | "DECLINED";
  response_label: string;
  attended: boolean | null;
}

export interface Meeting {
  id: number;
  number: string;
  title: string;
  agenda: string;
  organizer: number;
  organizer_name: string;
  starts_at: string;
  duration_minutes: number;
  status: "SCHEDULED" | "DONE" | "CANCELLED";
  status_label: string;
  notes: string;
  repeats_daily: boolean;
  attendees: Attendee[];
  my_response: Attendee["response"] | null;
  action_items: WorkTask[];
}

export interface Person {
  id: number;
  name: string;
  title: string;
  department: string;
  city: string;
  direct: boolean;
}

export interface ScoreRow {
  user_id: number;
  name: string;
  title: string;
  role: string;
  department: string;
  city: string;
  manager: string;
  direct_report: boolean;
  open_tasks: number;
  overdue_tasks: number;
  done_tasks: number;
  on_time_rate: number | null;
  tickets_resolved: number;
  documents_reviewed: number;
  meeting_attendance: number | null;
  avg_response_minutes: number | null;
  sla_met_rate: number | null;
  avg_review_hours: number | null;
  needs_guidance: boolean;
}

export interface Dashboard {
  days: number;
  totals: {
    people: number;
    open_tasks: number;
    overdue_tasks: number;
    done_tasks: number;
    on_time_rate: number | null;
    tickets_resolved: number;
    documents_reviewed: number;
    needs_guidance: number;
    avg_response_minutes: number | null;
  };
  departments: { department: string; people: number; open: number; overdue: number; done: number }[];
  people: ScoreRow[];
}

export const PRIORITY_TONE = { LOW: "neutral", NORMAL: "info", HIGH: "warning", URGENT: "danger" } as const;

/** A datetime-local input value `hours` from now, in local time. */
export function localInput(hours: number): string {
  const d = new Date(Date.now() + hours * 3_600_000);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export const toIso = (local: string) => new Date(local).toISOString();
