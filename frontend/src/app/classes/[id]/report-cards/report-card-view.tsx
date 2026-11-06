import type { ReportCard } from "@/lib/report-cards";
import type { ClassResults } from "@/lib/results";

// One student's report card, laid out for the screen and for paper. Shared by
// the single card and the whole-class print view.

type CardContext = Omit<ClassResults, "students"> & {
  school: { name: string };
  year: { name: string };
  position_out_of?: number;
};

export function ReportCardView({ data, card }: { data: CardContext; card: ReportCard }) {
  const kcse = data.scale.kind === "kcse";
  const headingId = `card-${card.id}`;
  const overall = card.overall;
  const { present, late, absent, days_recorded: days } = card.attendance;
  return (
    <article
      aria-labelledby={headingId}
      className="min-w-0 rounded-lg border border-rule-strong p-4 break-words sm:p-6 print:rounded-none print:border-0 print:p-0"
    >
      <header className="mb-4 border-b border-rule-strong pb-3">
        <p className="text-lg font-semibold">{data.school.name}</p>
        <p className="text-sm">
          Term {data.term.number} report, {data.year.name}
        </p>
        <h2 id={headingId} className="mt-3 text-xl font-semibold">
          {card.full_name}
        </h2>
        <p className="text-sm">
          Admission number {card.admission_number}, {data.class.name}
          {!card.in_class && " (no longer in this class)"}
        </p>
      </header>

      {/* Its own sideways scroll on narrow screens or with wide fonts, so it
          never pushes the card or the page wider. */}
      <div className="mb-4 overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Subject results</caption>
          <thead>
            <tr>
              <th scope="col" className={thClass}>
                Subject
              </th>
              <th scope="col" className={thClass}>
                Percentage
              </th>
              <th scope="col" className={thClass}>
                Grade
              </th>
              <th scope="col" className={thClass}>
                Points
              </th>
            </tr>
          </thead>
          <tbody>
            {data.subjects.length === 0 && (
              <tr>
                <td colSpan={4} className={tdClass}>
                  No assessments this term.
                </td>
              </tr>
            )}
            {data.subjects.map((subject) => {
              const result = card.results[subject.id];
              return (
                <tr key={subject.id}>
                  <th scope="row" className={`${tdClass} font-normal`}>
                    {subject.name}
                  </th>
                  <td className={tdClass}>{result ? `${result.percent}%` : "—"}</td>
                  <td className={`${tdClass} font-medium`}>{result ? result.grade : "—"}</td>
                  <td className={tdClass}>{result ? result.points : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <dl className="mb-4 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="font-medium">{kcse ? "Mean grade" : "Overall"}</dt>
        <dd>
          {overall ? (
            <>
              <span className="font-semibold">{overall.grade}</span>
              {!overall.complete && " (incomplete)"}, {overall.total_points} points,{" "}
              {overall.subjects_counted} subject{overall.subjects_counted === 1 ? "" : "s"}
            </>
          ) : (
            "No results yet"
          )}
        </dd>
        {data.show_positions && (
          <>
            <dt className="font-medium">Position</dt>
            <dd>
              {card.position != null
                ? `${card.position} of ${data.position_out_of}`
                : "None (only complete results are ranked)"}
            </dd>
          </>
        )}
        <dt className="font-medium">Attendance</dt>
        <dd>
          {days === 0
            ? "No registers recorded this term"
            : `Present ${present}, late ${late}, absent ${absent}, out of ${days} day${days === 1 ? "" : "s"} recorded`}
        </dd>
      </dl>

      <section aria-label="Class teacher's comment">
        <h3 className="mb-1 text-sm font-medium">Class teacher&apos;s comment</h3>
        {card.comment ? (
          <p className="text-sm whitespace-pre-line">{card.comment.text}</p>
        ) : (
          <p className="text-sm text-muted">No comment yet.</p>
        )}
      </section>

      <p className="mt-4 text-xs text-muted">Printed on {printedOn()}</p>
    </article>
  );
}

function printedOn(): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "long", timeZone: "Africa/Nairobi" }).format(new Date());
}

const thClass = "border-b border-rule-strong px-1.5 py-1.5 font-medium sm:px-2";
const tdClass = "border-b border-rule px-1.5 py-1.5 sm:px-2";
