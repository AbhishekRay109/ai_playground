import { Download, Play } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, ErrorNotice, SectionTitle, Spinner } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { MODES, toolLabel } from "../../lib/modes";
import { api, ApiError } from "../../services/api";
import type { CompareResult, EvalReport, Mode, ToolName } from "../../types/api";
import { Markdown } from "../chat/Markdown";
import { SourceList } from "../chat/SourceList";
import { AgentToolToggles } from "../chat/ModeSelector";

const METRIC_LABELS: Record<string, string> = {
  retrieval_hit_rate: "Retrieval hit rate",
  recall_at_k: "Recall@k",
  citation_validity: "Citation validity",
  completeness_estimate: "Completeness (estimate)",
  groundedness_estimate: "Groundedness (lexical estimate)",
  tool_selection_success_rate: "Tool-selection success",
  task_completion_rate: "Task completion",
  abstention_rate_on_unanswerable: "Correct abstention",
  latency_p50_ms: "Latency p50 (ms)",
  latency_p95_ms: "Latency p95 (ms)",
};

function fmt(v: unknown) {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
}

function CompareCard({ result }: { result: CompareResult }) {
  const r = result.response;
  const info = MODES.find((m) => m.id === result.mode)!;
  return (
    <Card className="flex min-w-0 flex-col p-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold">{info.label}</h4>
        {r && <span className="text-xs text-muted">{(r.latency_ms / 1000).toFixed(2)} s</span>}
      </div>
      {result.error ? (
        <ErrorNotice message={result.error.message} hint={result.error.hint} />
      ) : r ? (
        <>
          <div className="mb-2 flex flex-wrap gap-1">
            <Badge tone={r.status === "success" ? "ok" : "warn"}>{r.status}</Badge>
            {r.executed_tools.length ? (
              r.executed_tools.map((t) => (
                <Badge key={t} tone="ok">
                  ran: {toolLabel(t)}
                </Badge>
              ))
            ) : (
              <Badge>no tools</Badge>
            )}
            <Badge>
              ~{r.token_usage.prompt_tokens + r.token_usage.completion_tokens} tokens
              {r.token_usage.estimated ? " (est.)" : ""}
            </Badge>
            <Badge>{r.sources.length} sources</Badge>
          </div>
          <div className="max-h-72 overflow-y-auto">
            <Markdown text={r.answer} />
          </div>
          <dl className="mt-2 grid grid-cols-3 gap-1 text-[11px] text-muted">
            <div>chunks: {r.counts.retrieved_chunks}</div>
            <div>web: {r.counts.web_sources}</div>
            <div>rows: {r.counts.sql_rows}</div>
          </dl>
          {r.errors.length > 0 && <p className="mt-1 text-xs text-err">{r.errors.map((e) => e.message).join("; ")}</p>}
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer text-muted">Evidence ({r.sources.length})</summary>
            <SourceList sources={r.sources} />
          </details>
        </>
      ) : null}
    </Card>
  );
}

export function EvaluationView() {
  const [question, setQuestion] = useState("What does the travel policy say about exclusions?");
  const [modes, setModes] = useState<Mode[]>(["document_rag", "agent", "direct"]);
  const [tools, setTools] = useState<ToolName[]>(["document_retrieval", "web_search", "sql_query", "calculator"]);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<CompareResult[]>([]);
  const [error, setError] = useState<ApiError | null>(null);

  const datasets = useAsync(() => api.datasets(), []);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [benchRunning, setBenchRunning] = useState(false);
  const [benchError, setBenchError] = useState<ApiError | null>(null);

  const runCompare = async () => {
    setRunning(true);
    setError(null);
    setResults([]);
    try {
      setResults(await api.compare(question, modes, tools));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setRunning(false);
    }
  };

  const runBenchmark = async (name: string) => {
    setBenchRunning(true);
    setBenchError(null);
    try {
      setReport(await api.runDataset(name));
    } catch (err) {
      setBenchError(err as ApiError);
    } finally {
      setBenchRunning(false);
    }
  };

  const downloadReport = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([report.markdown], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `eval-${report.dataset}-${report.run_at.slice(0, 19)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <header>
        <h2 className="text-lg font-semibold">Evaluation</h2>
        <p className="text-sm text-muted">
          Run one question through several execution modes and compare answers, tools, evidence and latency. Automated
          quality scores are heuristics and are labelled as estimates.
        </p>
      </header>

      <Card className="space-y-3 p-4">
        <SectionTitle>Compare modes side by side</SectionTitle>
        <label htmlFor="eval-question" className="sr-only">
          Question
        </label>
        <textarea
          id="eval-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm"
        />
        <fieldset className="flex flex-wrap gap-2">
          <legend className="sr-only">Modes to compare</legend>
          {MODES.map((m) => (
            <label key={m.id} className="flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-sm">
              <input
                type="checkbox"
                checked={modes.includes(m.id)}
                onChange={(e) => setModes((prev) => (e.target.checked ? [...prev, m.id] : prev.filter((x) => x !== m.id)))}
              />
              {m.label}
            </label>
          ))}
        </fieldset>
        {modes.includes("agent") && <AgentToolToggles enabled={tools} onChange={setTools} />}
        <Button variant="primary" onClick={() => void runCompare()} disabled={running || !modes.length || !question.trim()}>
          {running ? <Spinner /> : <Play className="h-4 w-4" />} {running ? "Running modes sequentially…" : "Run comparison"}
        </Button>
        {error && <ErrorNotice message={error.message} hint={error.hint} />}
      </Card>

      {results.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {results.map((r) => (
            <CompareCard key={r.mode} result={r} />
          ))}
        </div>
      )}

      <Card className="space-y-3 p-4">
        <SectionTitle>Benchmark datasets</SectionTitle>
        {datasets.loading ? (
          <Spinner />
        ) : datasets.error ? (
          <ErrorNotice message={datasets.error.message} />
        ) : (
          <ul className="space-y-2">
            {datasets.data?.map((d) => (
              <li key={d.name} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{d.name}</p>
                  <p className="text-xs text-muted">
                    {d.description} {d.items} questions · modes: {d.modes.join(", ")}
                  </p>
                </div>
                <Button onClick={() => void runBenchmark(d.name)} disabled={benchRunning}>
                  {benchRunning ? <Spinner /> : <Play className="h-4 w-4" />} Run
                </Button>
              </li>
            ))}
          </ul>
        )}
        {benchRunning && <p className="text-xs text-muted">Running the benchmark. This calls the local model for every question.</p>}
        {benchError && <ErrorNotice message={benchError.message} hint={benchError.hint} />}
        {report && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted">
                {report.dataset} · model {report.model} · embeddings {report.embedding_model} ·{" "}
                {(report.duration_ms / 1000).toFixed(1)} s
              </p>
              <Button size="sm" onClick={downloadReport}>
                <Download className="h-3.5 w-3.5" /> Download report (.md)
              </Button>
            </div>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {Object.entries(report.summary).map(([k, v]) => (
                <div key={k} className="rounded-lg border border-border p-2">
                  <dt className="text-[11px] text-muted">{METRIC_LABELS[k] ?? k}</dt>
                  <dd className="text-lg font-semibold">{fmt(v)}</dd>
                </div>
              ))}
            </dl>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-xs">
                <thead>
                  <tr className="text-left text-muted">
                    {["Id", "Mode", "Status", "Tools executed", "Hit", "Recall@k", "Citations", "Completeness (est.)", "Tool choice", "ms"].map(
                      (h) => (
                        <th key={h} className="border-b border-border px-2 py-1.5">
                          {h}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {report.items.map((it) => (
                    <tr key={it.id} className="border-b border-border align-top">
                      <td className="px-2 py-1.5 font-mono">{it.id}</td>
                      <td className="px-2 py-1.5">{it.mode}</td>
                      <td className="px-2 py-1.5">{it.status}</td>
                      <td className="px-2 py-1.5">{it.executed_tools?.join(", ") || "-"}</td>
                      <td className="px-2 py-1.5">{fmt(it.retrieval_hit)}</td>
                      <td className="px-2 py-1.5">{fmt(it.recall_at_k)}</td>
                      <td className="px-2 py-1.5">{fmt(it.citation_validity)}</td>
                      <td className="px-2 py-1.5">{fmt(it.completeness_estimate)}</td>
                      <td className="px-2 py-1.5">{fmt(it.tool_selection_success)}</td>
                      <td className="px-2 py-1.5">{fmt(it.latency_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="text-xs text-muted">
              {report.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}
