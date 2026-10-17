import type { Mode, ToolName } from "../types/api";

export interface ModeInfo {
  id: Mode;
  label: string;
  short: string;
  description: string;
  examples: string[];
}

export const MODES: ModeInfo[] = [
  {
    id: "document_rag",
    label: "Document RAG",
    short: "RAG",
    description: "Answer using uploaded documents only.",
    examples: [
      "What does my uploaded policy say about exclusions?",
      "Summarize the key requirements in the security handbook.",
      "How far in advance must international travel be booked?",
    ],
  },
  {
    id: "web_search",
    label: "Web Search",
    short: "Web",
    description: "Search the web and answer from retrieved public pages.",
    examples: [
      "What changed recently in the Python ecosystem?",
      "What is the latest stable release of PostgreSQL?",
      "Summarize recent news about open-source LLMs.",
    ],
  },
  {
    id: "sql",
    label: "SQL Assistant",
    short: "SQL",
    description: "Answer using the configured read-only sample database.",
    examples: [
      "What was our highest-selling product by units?",
      "What was total revenue per year?",
      "Which country has the most customers?",
    ],
  },
  {
    id: "agent",
    label: "Agent Mode",
    short: "Agent",
    description: "Let the agent decide which enabled tools to use and in what order.",
    examples: [
      "Compare the uploaded policy with recent public guidance.",
      "What is 129 * 347?",
      "Which product earned the most revenue, and what is 15% of that amount?",
    ],
  },
  {
    id: "direct",
    label: "Direct LLM",
    short: "LLM",
    description: "Answer directly from the local model without retrieval or external tools.",
    examples: [
      "Explain the difference between RAG and fine-tuning.",
      "Write a Python function that checks for palindromes.",
      "What are embeddings, in two paragraphs?",
    ],
  },
];

export const modeInfo = (mode: Mode) => MODES.find((m) => m.id === mode)!;

export const TOOLS: { id: ToolName; label: string; description: string }[] = [
  { id: "document_retrieval", label: "Document retrieval", description: "Search uploaded documents" },
  { id: "web_search", label: "Web search", description: "Query SearXNG and read pages" },
  { id: "sql_query", label: "SQL query", description: "Read-only sample database" },
  { id: "calculator", label: "Calculator", description: "Safe arithmetic" },
];

const STEP_LABELS: Record<string, string> = {
  llm: "Language model",
  planner: "Planner",
  execution_summary: "Execution summary",
};

export const toolLabel = (name: string) => TOOLS.find((t) => t.id === name)?.label ?? STEP_LABELS[name] ?? name;
