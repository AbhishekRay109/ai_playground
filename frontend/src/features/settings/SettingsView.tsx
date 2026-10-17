import { RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNotice, SectionTitle, Spinner, StatusDot } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { api, ApiError } from "../../services/api";
import type { HealthResponse, RuntimeConfig } from "../../types/api";

function gb(bytes?: number | null) {
  return bytes ? `${(bytes / 1e9).toFixed(1)} GB` : "";
}

export function SettingsView({ health, onHealthReload }: { health?: HealthResponse; onHealthReload: () => void }) {
  const models = useAsync(() => api.models(), []);
  const config = useAsync(() => api.config(), []);
  const [form, setForm] = useState<RuntimeConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string[]>([]);

  useEffect(() => {
    if (config.data) setForm(config.data.runtime);
  }, [config.data]);

  const save = async () => {
    if (!form || !config.data) return;
    setSaving(true);
    setError(null);
    setNotice([]);
    const changed = Object.fromEntries(
      Object.entries(form).filter(([k, v]) => config.data!.runtime[k as keyof RuntimeConfig] !== v),
    ) as Partial<RuntimeConfig>;
    try {
      const res = await api.updateConfig(changed);
      config.setData(res);
      setNotice(res.warnings.length ? res.warnings : ["Settings saved."]);
      onHealthReload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setSaving(false);
    }
  };

  const set = <K extends keyof RuntimeConfig>(key: K, value: RuntimeConfig[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const installed = models.data?.models ?? [];
  const modelMissing = form && models.data?.available && !installed.some((m) => m.name === form.chat_model);

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-4 sm:p-6">
      <header>
        <h2 className="text-lg font-semibold">Models and settings</h2>
        <p className="text-sm text-muted">
          All inference runs locally. Models are never downloaded automatically; install them with Ollama first.
        </p>
      </header>

      <Card className="p-4">
        <SectionTitle
          action={
            <Button size="sm" variant="ghost" onClick={onHealthReload} aria-label="Refresh status">
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          }
        >
          Connection status
        </SectionTitle>
        {!health ? (
          <Spinner />
        ) : (
          <ul className="space-y-2">
            {Object.entries(health.services).map(([name, s]) => (
              <li key={name} className="flex items-start gap-2 text-sm">
                <span className="mt-1.5">
                  <StatusDot ok={s.ok} />
                </span>
                <div>
                  <p>
                    <span className="font-medium">{name}</span> <span className="text-muted">{s.detail}</span>
                  </p>
                  {s.hint && <p className="text-xs text-warn">{s.hint}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-4">
        <SectionTitle>Installed Ollama models</SectionTitle>
        {models.loading ? (
          <Spinner />
        ) : !models.data?.available ? (
          <ErrorNotice
            title="Ollama is not available"
            message={models.data?.error ?? models.error?.message ?? "Unknown error"}
            hint={models.data?.hint ?? undefined}
            onRetry={() => void models.reload()}
          />
        ) : installed.length === 0 ? (
          <p className="text-sm text-muted">
            No models installed. Run <code className="font-mono">ollama pull qwen2.5:7b</code> and refresh.
          </p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {installed.map((m) => (
              <li key={m.name}>
                <button
                  type="button"
                  onClick={() => set("chat_model", m.name)}
                  aria-pressed={form?.chat_model === m.name}
                  className={`w-full rounded-lg border p-2 text-left text-sm ${
                    form?.chat_model === m.name ? "border-accent bg-accent-soft/50" : "border-border hover:bg-surface-2"
                  }`}
                >
                  <span className="font-mono">{m.name}</span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {m.parameter_size && <Badge>{m.parameter_size}</Badge>}
                    {m.quantization && <Badge>{m.quantization}</Badge>}
                    {m.family && <Badge>{m.family}</Badge>}
                    {m.size_bytes && <Badge>{gb(m.size_bytes)}</Badge>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">
          Licenses differ between models (e.g. Llama Community License, Apache-2.0 for Qwen 2.5 and Mistral 7B, Gemma
          Terms of Use). Check the license of each model you install.
        </p>
      </Card>

      <Card className="p-4">
        <SectionTitle>Generation and retrieval</SectionTitle>
        {config.error && <ErrorNotice message={config.error.message} onRetry={() => void config.reload()} />}
        {form && (
          <form
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label className="text-sm">
              Chat model
              <input
                className="mt-1 w-full rounded-lg border border-border bg-bg px-2 py-1.5 font-mono text-sm"
                value={form.chat_model}
                onChange={(e) => set("chat_model", e.target.value)}
              />
              {modelMissing && <span className="text-xs text-warn">Not installed in Ollama.</span>}
            </label>
            <label className="text-sm">
              Temperature: {form.temperature.toFixed(2)}
              <input
                type="range"
                min={0}
                max={1.5}
                step={0.05}
                value={form.temperature}
                onChange={(e) => set("temperature", Number(e.target.value))}
                className="mt-2 w-full accent-[var(--color-accent)]"
              />
            </label>
            <label className="text-sm">
              Max output tokens
              <input
                type="number"
                min={16}
                max={8192}
                className="mt-1 w-full rounded-lg border border-border bg-bg px-2 py-1.5 text-sm"
                value={form.max_tokens}
                onChange={(e) => set("max_tokens", Number(e.target.value))}
              />
            </label>
            <label className="text-sm">
              Request timeout (seconds)
              <input
                type="number"
                min={5}
                max={900}
                className="mt-1 w-full rounded-lg border border-border bg-bg px-2 py-1.5 text-sm"
                value={form.llm_timeout_s}
                onChange={(e) => set("llm_timeout_s", Number(e.target.value))}
              />
            </label>
            <label className="text-sm">
              Embedding model ({config.data?.embedding_provider})
              <input
                className="mt-1 w-full rounded-lg border border-border bg-bg px-2 py-1.5 font-mono text-sm"
                value={form.embedding_model}
                onChange={(e) => set("embedding_model", e.target.value)}
              />
              <span className="text-xs text-muted">Changing it marks existing documents for re-indexing.</span>
            </label>
            <label className="text-sm">
              Retrieval top-k
              <input
                type="number"
                min={1}
                max={20}
                className="mt-1 w-full rounded-lg border border-border bg-bg px-2 py-1.5 text-sm"
                value={form.rag_top_k}
                onChange={(e) => set("rag_top_k", Number(e.target.value))}
              />
            </label>
            <label className="text-sm">
              Similarity threshold: {form.rag_score_threshold.toFixed(2)}
              <input
                type="range"
                min={0}
                max={0.9}
                step={0.05}
                value={form.rag_score_threshold}
                onChange={(e) => set("rag_score_threshold", Number(e.target.value))}
                className="mt-2 w-full accent-[var(--color-accent)]"
              />
            </label>
            <div className="flex items-end gap-2 sm:col-span-2">
              <Button type="submit" variant="primary" disabled={saving}>
                {saving ? <Spinner /> : <Save className="h-4 w-4" />} Save settings
              </Button>
              <Button
                onClick={async () => {
                  const res = await api.resetConfig();
                  config.setData(res);
                }}
              >
                Reset to defaults
              </Button>
            </div>
          </form>
        )}
        {error && (
          <div className="mt-3">
            <ErrorNotice message={error.message} hint={error.hint} />
          </div>
        )}
        {notice.length > 0 && (
          <ul className="mt-3 text-sm text-ok" role="status">
            {notice.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </Card>

      {config.data && (
        <Card className="p-4">
          <SectionTitle>Limits (from environment)</SectionTitle>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {Object.entries(config.data.limits).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2 border-b border-border py-1">
                <dt className="text-muted">{k}</dt>
                <dd className="font-mono">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-xs text-muted">
            Vector store: {config.data.vector_store} · Ollama: {config.data.ollama_base_url} · SearXNG:{" "}
            {config.data.searxng_url}
          </p>
        </Card>
      )}
    </div>
  );
}
