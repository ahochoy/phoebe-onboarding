import type { ReactNode } from "react";
import { Link } from "react-router";
import { QueryError } from "../components/QueryError";
import { useAdminDocuments } from "./DocumentsTab";
import { useGroups } from "./GroupsTab";
import { usePeople } from "./PeopleTab";
import { summarize } from "./summary";

function Card({
  to,
  title,
  value,
  detail,
}: {
  to: string;
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <Link
      to={to}
      className="block rounded-lg bg-highlight-soft p-4 outline-offset-2 hover:bg-highlight-soft/70"
    >
      <span className="block text-sm font-medium text-ink/80">{title}</span>
      <span className="block text-4xl font-semibold text-accent">{value}</span>
      <span className="block text-sm text-ink/80">{detail}</span>
    </Link>
  );
}

export function HomeTab() {
  const people = usePeople();
  const docs = useAdminDocuments();
  const groups = useGroups();

  const ready = people.data && docs.data && groups.data;
  const s = ready ? summarize(people.data, docs.data, groups.data) : null;
  const errors: ReactNode[] = [people, docs, groups]
    .filter((q) => q.error)
    .map((q, i) => <QueryError key={i} error={q.error} stale={Boolean(s)} />);

  return (
    <section aria-labelledby="home-heading" className="space-y-4">
      <h2 id="home-heading" className="text-lg font-semibold">
        Home
      </h2>
      {errors}
      {s ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Card
            to="/admin/people"
            title="People onboarding"
            value={String(s.people)}
            detail={`${s.stillOnboarding} still onboarding · ${s.avgCompletion}% average`}
          />
          <Card
            to="/admin/documents"
            title="Documents"
            value={String(s.documents)}
            detail={[
              `${s.indexed} indexed`,
              s.processing > 0 ? `${s.processing} processing` : null,
              s.failed > 0 ? `${s.failed} failed` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          />
          <Card
            to="/admin/groups"
            title="Groups"
            value={String(s.groups)}
            detail="across the org"
          />
          <Card
            to="/admin/people"
            title="Task completion"
            value={`${s.taskCompletion}%`}
            detail="of assigned tasks done"
          />
        </div>
      ) : errors.length === 0 ? (
        <p role="status" className="text-sm text-ink/80">
          Loading summary…
        </p>
      ) : null}
    </section>
  );
}
