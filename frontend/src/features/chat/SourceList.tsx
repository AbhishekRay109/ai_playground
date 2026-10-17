import { Database, ExternalLink, FileText, Globe } from "lucide-react";
import { Badge } from "../../components/ui";
import type { Source } from "../../types/api";

export function SourceList({ sources, compact = false }: { sources: Source[]; compact?: boolean }) {
  if (!sources.length) return null;
  const shown = compact ? sources.filter((s) => s.cited) : sources;
  const list = shown.length ? shown : sources;
  return (
    <ol className="mt-3 space-y-1.5" aria-label="Sources">
      {list.map((s) => (
        <li key={`${s.kind}-${s.id}`} className="rounded-lg border border-border bg-surface-2/60 px-2.5 py-2 text-xs">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[11px] text-accent">[{s.id}]</span>
            {s.kind === "document" && <FileText className="h-3.5 w-3.5 text-muted" aria-hidden />}
            {s.kind === "web" && <Globe className="h-3.5 w-3.5 text-muted" aria-hidden />}
            {s.kind === "sql" && <Database className="h-3.5 w-3.5 text-muted" aria-hidden />}
            {s.kind === "web" && s.url ? (
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="inline-flex min-w-0 items-center gap-1 font-medium hover:underline"
              >
                <span className="truncate">{s.title}</span>
                <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
              </a>
            ) : (
              <span className="font-medium">{s.filename ?? s.title}</span>
            )}
            {s.page != null && <Badge>page {s.page}</Badge>}
            {s.content_type && <Badge tone={s.content_type === "page" ? "ok" : "warn"}>{s.content_type}</Badge>}
            {s.score != null && <Badge>score {s.score.toFixed(2)}</Badge>}
            {s.row_count != null && <Badge>{s.row_count} rows</Badge>}
            {s.published_date && <Badge>{s.published_date.slice(0, 10)}</Badge>}
            {!s.cited && <Badge>not cited</Badge>}
          </div>
          {s.kind === "web" && s.url && <p className="mt-0.5 truncate text-[11px] text-muted">{s.url}</p>}
          <p className="mt-1 line-clamp-3 text-muted">{s.excerpt}</p>
        </li>
      ))}
    </ol>
  );
}
