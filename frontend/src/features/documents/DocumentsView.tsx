import clsx from "clsx";
import { FileUp, RefreshCw, Trash2 } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Badge, Button, Card, ErrorNotice, SectionTitle, Spinner } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api, ApiError } from "../../services/api";
import type { IngestResult } from "../../types/api";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown";

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function DocumentsView({ onChange }: { onChange?: () => void }) {
  const docs = useAsync(() => api.documents(), []);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<IngestResult[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setError(null);
    try {
      const res = await api.uploadDocuments(files);
      setResults(res.results);
      await docs.reload();
      onChange?.();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void upload(Array.from(e.dataTransfer.files));
  };

  const remove = async (id: string) => {
    setBusyId(id);
    try {
      await api.deleteDocument(id);
      await docs.reload();
      onChange?.();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusyId(null);
    }
  };

  const reindex = async (id: string) => {
    setBusyId(id);
    try {
      await api.reindexDocument(id);
      await docs.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 sm:p-6">
      <header>
        <h2 className="text-lg font-semibold">Documents</h2>
        <p className="text-sm text-muted">
          Uploaded files are extracted, chunked and embedded locally, then stored in Qdrant. Content is treated as
          untrusted data: instructions inside documents are never followed.
        </p>
      </header>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 text-center",
          dragging ? "border-accent bg-accent-soft/40" : "border-border",
        )}
      >
        <FileUp className="h-8 w-8 text-muted" aria-hidden />
        <p className="text-sm">Drag and drop PDF, DOCX, TXT or Markdown files here</p>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          id="file-upload"
          onChange={(e) => void upload(Array.from(e.target.files ?? []))}
        />
        <Button onClick={() => input.current?.click()} disabled={uploading}>
          {uploading ? <Spinner /> : <FileUp className="h-4 w-4" />} {uploading ? "Processing…" : "Choose files"}
        </Button>
      </div>

      {error && <ErrorNotice message={error.message} hint={error.hint} />}

      {results.length > 0 && (
        <Card className="p-3">
          <SectionTitle>Last upload</SectionTitle>
          <ul className="space-y-1 text-sm">
            {results.map((r, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Badge tone={r.status === "ready" ? "ok" : r.status === "duplicate" ? "warn" : "err"}>{r.status}</Badge>
                <span className="font-medium">{r.filename}</span>
                {r.status === "ready" && (
                  <span className="text-xs text-muted">
                    {r.chunk_count} chunks{r.page_count ? ` · ${r.page_count} pages` : ""} · {r.latency_ms} ms
                  </span>
                )}
                {r.status === "duplicate" && <span className="text-xs text-muted">already uploaded (same content hash)</span>}
                {r.error && <span className="text-xs text-err">{r.error}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <section>
        <SectionTitle
          action={
            <Button variant="ghost" size="sm" onClick={() => void docs.reload()} aria-label="Refresh documents">
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          }
        >
          Library
        </SectionTitle>
        {docs.loading && !docs.data ? (
          <Spinner />
        ) : docs.error ? (
          <ErrorNotice message={docs.error.message} hint={docs.error.hint} onRetry={() => void docs.reload()} />
        ) : !docs.data?.length ? (
          <p className="text-sm text-muted">No documents yet.</p>
        ) : (
          <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
            {docs.data.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{d.filename}</p>
                  <p className="text-xs text-muted">
                    {d.content_type.toUpperCase()} · {formatBytes(d.size_bytes)} · {d.chunk_count} chunks
                    {d.page_count ? ` · ${d.page_count} pages` : ""} · {new Date(d.created_at).toLocaleString()}
                  </p>
                  <p className="truncate font-mono text-[11px] text-muted">
                    {d.embedding_model} · sha256 {d.content_hash.slice(0, 12)}…
                  </p>
                </div>
                {d.stale && (
                  <Button size="sm" onClick={() => void reindex(d.id)} disabled={busyId === d.id}>
                    <RefreshCw className="h-3.5 w-3.5" /> Re-index
                  </Button>
                )}
                {d.stale && <Badge tone="warn">embedded with another model</Badge>}
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => void remove(d.id)}
                  disabled={busyId === d.id}
                  aria-label={`Delete ${d.filename}`}
                >
                  {busyId === d.id ? <Spinner /> : <Trash2 className="h-3.5 w-3.5" />} Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
