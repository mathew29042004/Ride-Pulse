/** Driver Academy: short courses with a quiz. Induction is required before the first ride (and
 * yearly); the accessibility course makes you assist-trained. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ArrowLeft, Award, BookOpen, CheckCircle2, Clock } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { t } from "@/lib/i18n";

interface Row {
  slug: string;
  title: string;
  minutes: number;
  required: boolean;
  lessons: number;
  questions: number;
  passed_on: string | null;
  score: number | null;
  due: boolean;
}
interface Course {
  slug: string;
  title: string;
  lessons: { title: string; body: string }[];
  questions: { question: string; options: string[] }[];
}
interface Result {
  score: number;
  passed: boolean;
  pass_percent: number;
  review: { question: string; answer: string }[];
}

export function useAcademy() {
  return useQuery({ queryKey: ["driver", "academy"], queryFn: () => api.get<Row[]>("driver/academy/") });
}

/** On the driver home: induction is due, so going online is blocked until it's done. */
export function InductionDueCard() {
  const rows = useAcademy().data;
  const induction = rows?.find((r) => r.slug === "induction");
  if (!induction?.due) return null;
  return (
    <Link to="/drive/academy" className="mb-3 flex items-center gap-3 rounded-2xl bg-amber-500/15 p-3 text-sm text-amber-900 dark:text-amber-200">
      <BookOpen className="size-5 shrink-0" />
      <span className="flex-1">
        <span className="block font-semibold">{induction.passed_on ? t("Your yearly refresher is due") : t("Finish induction training")}</span>
        <span className="text-xs">{t("{m} minutes, required before you can go online", { m: induction.minutes })}</span>
      </span>
    </Link>
  );
}

export default function DriverAcademy() {
  const rows = useAcademy();
  const [open, setOpen] = useState<string | null>(null);
  if (open) return <CourseView slug={open} onBack={() => setOpen(null)} />;
  return (
    <div className="mx-auto max-w-xl px-4 pb-24 pt-3">
      <div className="flex items-center gap-2">
        <Link to="/drive/account" className="flex size-10 items-center justify-center rounded-full bg-surface-2" aria-label={t("Back")}>
          <ArrowLeft className="size-5" />
        </Link>
        <div>
          <h1 className="text-lg font-bold">{t("Driver Academy")}</h1>
          <p className="text-xs text-muted">{t("Short courses, a quiz, a certificate. Pass with 80%.")}</p>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {(rows.data ?? []).map((c) => (
          <button key={c.slug} onClick={() => setOpen(c.slug)} className={clsx("flex w-full items-center gap-3 rounded-2xl border p-4 text-left", c.due ? "border-amber-500" : "border-line")}>
            {c.passed_on && !c.due ? <Award className="size-6 shrink-0 text-brand" /> : <BookOpen className="size-6 shrink-0 text-muted" />}
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">
                {c.title} {c.required && <span className="ml-1 rounded bg-surface-3 px-1.5 text-[10px] uppercase">{t("required")}</span>}
              </span>
              <span className="text-xs text-muted">
                <Clock className="mr-1 inline size-3" />
                {c.minutes} min · {c.lessons} {t("lessons")} · {c.questions} {t("questions")}
                {c.passed_on && ` · ${t("passed {date} ({score}%)", { date: c.passed_on, score: c.score ?? 0 })}`}
              </span>
            </span>
            {c.due && <span className="text-xs font-semibold text-amber-600">{t("due")}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

function CourseView({ slug, onBack }: { slug: string; onBack: () => void }) {
  const qc = useQueryClient();
  const course = useQuery({ queryKey: ["driver", "course", slug], queryFn: () => api.get<Course>(`driver/academy/${slug}/`) });
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<Result | null>(null);
  const submit = useMutation({
    mutationFn: () => api.post<Result>(`driver/academy/${slug}/submit/`, { answers: (course.data?.questions ?? []).map((_, i) => answers[i] ?? -1) }),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["driver"] });
      if (r.passed) toast.success(t("Passed! Certificate added."));
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t("Something went wrong.")),
  });
  const c = course.data;
  if (!c) return <div className="p-6 text-center text-sm text-muted">{t("Loading…")}</div>;
  const complete = c.questions.every((_, i) => answers[i] !== undefined);
  return (
    <div className="mx-auto max-w-xl px-4 pb-24 pt-3">
      <button onClick={onBack} className="mb-2 flex items-center gap-1 text-sm text-muted">
        <ArrowLeft className="size-4" /> {t("All courses")}
      </button>
      <h1 className="text-xl font-bold">{c.title}</h1>
      <div className="mt-4 space-y-4">
        {c.lessons.map((l, i) => (
          <div key={i} className="rounded-2xl bg-surface-2 p-4">
            <div className="text-sm font-semibold">
              {i + 1}. {l.title}
            </div>
            <p className="mt-1 text-sm leading-relaxed">{l.body}</p>
          </div>
        ))}
      </div>
      <h2 className="mt-6 font-bold">{t("Quiz")}</h2>
      <div className="mt-2 space-y-4">
        {c.questions.map((q, i) => (
          <fieldset key={i}>
            <legend className="mb-1 text-sm font-semibold">
              {i + 1}. {q.question}
            </legend>
            {q.options.map((o, j) => (
              <label key={j} className="flex items-center gap-2 py-1 text-sm">
                <input type="radio" name={`q${i}`} checked={answers[i] === j} onChange={() => setAnswers({ ...answers, [i]: j })} disabled={!!result?.passed} />
                {o}
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      {result && (
        <div className={clsx("mt-4 rounded-2xl p-4 text-sm", result.passed ? "bg-brand/15" : "bg-danger/10")}>
          <div className="flex items-center gap-2 font-semibold">
            {result.passed && <CheckCircle2 className="size-5 text-brand" />}
            {result.passed ? t("Passed with {score}%", { score: result.score }) : t("{score}%: you need {pass}% to pass. Review and try again.", { score: result.score, pass: result.pass_percent })}
          </div>
          {result.review.map((r) => (
            <p key={r.question} className="mt-1 text-xs">
              {r.question} → <b>{r.answer}</b>
            </p>
          ))}
        </div>
      )}
      {!result?.passed && (
        <Button className="mt-4" block size="lg" loading={submit.isPending} disabled={!complete} onClick={() => submit.mutate()}>
          {t("Submit answers")}
        </Button>
      )}
    </div>
  );
}
