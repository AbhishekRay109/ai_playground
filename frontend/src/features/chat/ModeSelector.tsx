import clsx from "clsx";
import { Bot, Database, FileText, Globe, MessageSquare } from "lucide-react";
import { MODES, TOOLS } from "../../lib/modes";
import type { Mode, ToolName } from "../../types/api";
import { Switch } from "../../components/ui";

export const MODE_ICONS: Record<Mode, typeof FileText> = {
  document_rag: FileText,
  web_search: Globe,
  sql: Database,
  agent: Bot,
  direct: MessageSquare,
};

export function ModeSelector({ value, onChange }: { value: Mode; onChange: (m: Mode) => void }) {
  return (
    <div role="radiogroup" aria-label="Execution mode" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {MODES.map((m) => {
        const Icon = MODE_ICONS[m.id];
        const selected = value === m.id;
        return (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(m.id)}
            className={clsx(
              "group rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent",
              selected ? "border-accent bg-accent-soft/60" : "border-border bg-surface hover:border-muted/50",
            )}
          >
            <span className="flex items-center gap-2">
              <Icon className={clsx("h-4 w-4", selected ? "text-accent" : "text-muted")} aria-hidden />
              <span className="text-sm font-medium">{m.label}</span>
            </span>
            <span className="mt-1 block text-xs leading-snug text-muted">{m.description}</span>
          </button>
        );
      })}
    </div>
  );
}

export function AgentToolToggles({
  enabled,
  onChange,
}: {
  enabled: ToolName[];
  onChange: (tools: ToolName[]) => void;
}) {
  const toggle = (id: ToolName, on: boolean) =>
    onChange(on ? [...enabled.filter((t) => t !== id), id] : enabled.filter((t) => t !== id));
  return (
    <fieldset className="rounded-xl border border-border bg-surface p-2">
      <legend className="px-1 text-xs text-muted">
        Tools <em>available</em> to the agent. The agent decides whether to use them.
      </legend>
      <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-4">
        {TOOLS.map((t) => (
          <Switch
            key={t.id}
            id={`tool-${t.id}`}
            label={t.label}
            description={t.description}
            checked={enabled.includes(t.id)}
            onChange={(v) => toggle(t.id, v)}
          />
        ))}
      </div>
    </fieldset>
  );
}
