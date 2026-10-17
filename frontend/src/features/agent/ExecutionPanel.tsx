import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ChevronDown, CircleSlash, Clock, Loader2, X, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Badge, Button, SectionTitle } from "../../components/ui";
import type { UiMessage } from "../../hooks/useChat";
import { modeInfo, toolLabel } from "../../lib/modes";
import type { ExecutionStep, StepStatus } from "../../types/api";
import { SourceList } from "../chat/SourceList";

const STATUS_ICON: Record<StepStatus, ReactNode> = {
  running: <Loader2 className="h-4 w-4 animate-spin text-muted" aria-label="running" />,
  success: <CheckCircle2 className="h-4 w-4 text-ok" aria-label="success" />,
  error: <XCircle className="h-4 w-4 text-err" aria-label="error" />,
  timeout: <Clock className="h-4 w-4 text-err" aria-label="timeout" />,
  rejected: <CircleSlash className="h-4 w-4 text-warn" aria-label="rejected" />,
  skipped: <CircleSlash className="h-4 w-4 text-muted" aria-label="skipped" />,
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-xs">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

function ToolChips({ tools, tone, empty }: { tools: string[]; tone?: "ok" | "neutral" | "warn"; empty: string }) {
  if (!tools.length) return <span className="text-muted">{empty}</span>;
  return (
    <span className="flex flex-wrap justify-end gap-1">
      {tools.map((t) => (
        <Badge key={t} tone={tone}>
          {toolLabel(t)}
        </Badge>
      ))}
    </span>
  );
}

function StepDetails({ step }: { step: ExecutionStep }) {
  const d = step.details as Record<string, any>;
  return (
    <div className="mt-2 space-y-2 text-xs">
      {step.input_summary && (
        <p>
          <span className="text-muted">Input: </span>
          <code className="break-all font-mono">{step.input_summary}</code>
        </p>
      )}
      {Array.isArray(d.chunks) && d.chunks.length > 0 && (
        <div>
          <p className="mb-1 text-muted">
            Retrieved chunks (top_k {d.top_k}, threshold {d.score_threshold}, {d.candidates} candidates)
          </p>
          <ol className="space-y-1.5">
            {d.chunks.map((c: any) => (
              <li key={c.chunk_id} className="rounded-md border border-border bg-bg/60 p-2">
                <div className="mb-1 flex flex-wrap gap-1">
                  <Badge>{c.filename}</Badge>
                  {c.page != null && <Badge>page {c.page}</Badge>}
                  <Badge>chunk #{c.chunk_index}</Badge>
                  <Badge tone="accent">score {Number(c.score).toFixed(3)}</Badge>
                </div>
                <p className="line-clamp-6 whitespace-pre-wrap text-muted">{c.text}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
      {Array.isArray(d.results) && d.results.length > 0 && (
        <div>
          <p className="mb-1 text-muted">Search results for “{d.query}”</p>
          <ol className="space-y-1.5">
            {d.results.map((r: any) => (
              <li key={r.url} className="rounded-md border border-border bg-bg/60 p-2">
                <a href={r.url} target="_blank" rel="noopener noreferrer nofollow" className="font-medium hover:underline">
                  {r.title}
                </a>
                <p className="truncate text-[11px] text-muted">{r.url}</p>
                <div className="my-1 flex flex-wrap gap-1">
                  <Badge tone={r.fetch_status === "ok" ? "ok" : r.fetch_status === "not_fetched" ? "neutral" : "warn"}>
                    page: {r.fetch_status}
                  </Badge>
                  {r.engine && <Badge>{r.engine}</Badge>}
                  {r.published_date && <Badge>{String(r.published_date).slice(0, 10)}</Badge>}
                </div>
                {r.snippet && <p className="text-muted">Snippet: {r.snippet}</p>}
                {r.fetch_error && <p className="text-warn">{r.fetch_error}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}
      {d.sql && (
        <div>
          <p className="mb-1 text-muted">Validated SQL</p>
          <pre className="overflow-x-auto rounded-md bg-[#0d1117] p-2 font-mono text-[11px] text-slate-200">{d.sql}</pre>
        </div>
      )}
      {Array.isArray(d.attempts) && d.attempts.some((a: any) => a.status !== "success") && (
        <ul className="space-y-1">
          {d.attempts.map((a: any, i: number) => (
            <li key={i} className="rounded-md border border-warn/40 p-1.5">
              <Badge tone={a.status === "success" ? "ok" : "warn"}>attempt {i + 1}: {a.status}</Badge>
              {a.error && <p className="mt-1 text-warn">{a.error}</p>}
              <code className="mt-1 block break-all font-mono text-[11px] text-muted">{a.sql}</code>
            </li>
          ))}
        </ul>
      )}
      {Array.isArray(d.columns) && Array.isArray(d.rows) && (
        <div className="overflow-x-auto">
          <p className="mb-1 text-muted">
            {d.row_count} row(s){d.truncated ? " (truncated at the row limit)" : ""}
          </p>
          <table className="w-full border-collapse font-mono text-[11px]">
            <thead>
              <tr>
                {d.columns.map((c: string) => (
                  <th key={c} className="border border-border px-1.5 py-1 text-left">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.slice(0, 25).map((row: unknown[], i: number) => (
                <tr key={i}>
                  {row.map((v, j) => (
                    <td key={j} className="border border-border px-1.5 py-0.5">
                      {v === null ? "NULL" : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.result !== undefined && d.expression && (
        <p className="font-mono">
          {d.expression} = <strong>{String(d.result)}</strong>
        </p>
      )}
      {Array.isArray(d.notes) && d.notes.length > 0 && (
        <ul className="text-warn">
          {d.notes.map((n: string, i: number) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {d.hint && <p className="text-muted">Hint: {d.hint}</p>}
    </div>
  );
}

function StepItem({ step }: { step: ExecutionStep }) {
  const [open, setOpen] = useState(false);
  const hasDetails = step.input_summary || Object.keys(step.details ?? {}).length > 0;
  return (
    <li className="rounded-lg border border-border bg-surface-2/50 p-2">
      <button
        type="button"
        className="flex w-full items-start gap-2 text-left"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        disabled={!hasDetails}
      >
        <span className="mt-0.5">{STATUS_ICON[step.status]}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="font-medium">{toolLabel(step.name)}</span>
            <Badge>{step.kind}</Badge>
            <Badge tone={step.status === "success" ? "ok" : step.status === "running" ? "neutral" : step.status === "rejected" ? "warn" : "err"}>
              {step.status}
            </Badge>
            {step.latency_ms != null && <span className="text-muted">{step.latency_ms} ms</span>}
          </span>
          {step.purpose && <span className="block text-xs text-muted">{step.purpose}</span>}
          {step.result_summary && <span className="mt-0.5 block text-xs">{step.result_summary}</span>}
        </span>
        {hasDetails && (
          <ChevronDown className={clsx("mt-0.5 h-4 w-4 shrink-0 text-muted transition-transform", open && "rotate-180")} />
        )}
      </button>
      {open && <StepDetails step={step} />}
    </li>
  );
}

export function ExecutionPanel({
  message,
  onClose,
  availableTools,
}: {
  message?: UiMessage;
  onClose?: () => void;
  availableTools: string[];
}) {
  return (
    <aside aria-label="Execution details" className="flex h-full flex-col bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Execution details</h2>
        {onClose && (
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close execution details">
            <X className="h-4 w-4" />
          </Button>
        )}
      </div>
      {!message ? (
        <p className="p-4 text-sm text-muted">
          Ask a question, then open an answer's trace to see the selected mode, the tools that actually ran, retrieved
          evidence and latency.
        </p>
      ) : (
        <ExecutionBody message={message} availableTools={availableTools} />
      )}
    </aside>
  );
}

function ExecutionBody({ message, availableTools }: { message: UiMessage; availableTools: string[] }) {
  const r = message.response;
  const steps = message.steps;
  const toolSteps = steps.filter((s) => s.kind === "tool");
  const executed = r?.executed_tools ?? [
    ...new Set(toolSteps.filter((s) => !["rejected", "running"].includes(s.status)).map((s) => s.name)),
  ];
  const available = r ? r.available_tools : message.mode === "agent" ? availableTools : [];
  const selected = r?.selected_tools ?? [];
  const status = message.status === "streaming" ? "running" : (r?.status ?? message.status);
  return (
    <div className="flex-1 space-y-5 overflow-y-auto p-4">
      <section>
        <SectionTitle>Summary</SectionTitle>
        <dl className="divide-y divide-border">
          <Row label="Selected mode">{modeInfo(message.mode).label}</Row>
          <Row label="Status">
            <Badge tone={status === "success" ? "ok" : status === "running" ? "neutral" : status === "partial" ? "warn" : "err"}>
              {status}
            </Badge>
          </Row>
          {message.mode === "agent" && (
            <>
              <Row label="Tools available">
                <ToolChips tools={available} empty="none enabled" />
              </Row>
              <Row label="Tools requested">
                <ToolChips tools={selected} tone="neutral" empty="none" />
              </Row>
            </>
          )}
          <Row label="Tools executed">
            <ToolChips tools={executed} tone="ok" empty="none" />
          </Row>
          {r && (
            <>
              <Row label="Retrieved chunks">{r.counts.retrieved_chunks}</Row>
              <Row label="Web sources">{r.counts.web_sources}</Row>
              <Row label="SQL rows">{r.counts.sql_rows}</Row>
              <Row label="Model">{r.model ?? "n/a"}</Row>
              {r.embedding_model && <Row label="Embedding model">{r.embedding_model}</Row>}
              <Row label="Total latency">{r.latency_ms} ms</Row>
              <Row label="Tokens">
                {r.token_usage.prompt_tokens} in / {r.token_usage.completion_tokens} out
                {r.token_usage.estimated && " (estimated)"}
              </Row>
              {r.citations.total_markers > 0 && (
                <Row label="Citations">
                  {r.citations.valid_markers}/{r.citations.total_markers} valid
                  {r.citations.invalid_markers.length > 0 && ` (removed ${r.citations.invalid_markers.join(", ")})`}
                </Row>
              )}
            </>
          )}
        </dl>
      </section>

      <section>
        <SectionTitle>Execution trace</SectionTitle>
        {steps.length ? (
          <ol className="space-y-1.5">
            {steps.map((s) => (
              <StepItem key={s.id} step={s} />
            ))}
          </ol>
        ) : (
          <p className="text-xs text-muted">No steps yet.</p>
        )}
      </section>

      {r && (r.errors.length > 0 || r.warnings.length > 0) && (
        <section>
          <SectionTitle>Errors and warnings</SectionTitle>
          <ul className="space-y-1 text-xs">
            {r.errors.map((e, i) => (
              <li key={`e${i}`} className="flex gap-1.5 text-err">
                <XCircle className="h-3.5 w-3.5 shrink-0" /> {e.message} <span className="text-muted">({e.code})</span>
              </li>
            ))}
            {r.warnings.map((w, i) => (
              <li key={`w${i}`} className="flex gap-1.5 text-warn">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {w}
              </li>
            ))}
          </ul>
        </section>
      )}

      {message.sources.length > 0 && (
        <section>
          <SectionTitle>Sources and evidence</SectionTitle>
          <SourceList sources={message.sources} />
        </section>
      )}
    </div>
  );
}
