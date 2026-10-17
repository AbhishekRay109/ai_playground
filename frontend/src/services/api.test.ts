import { response, sseResponse } from "../test/fixtures";
import { api, ApiError, parseSSE } from "./api";

test("parseSSE handles events split across chunks", async () => {
  const res = sseResponse([
    { type: "session", session_id: "s", message_id: "m" },
    { type: "delta", text: "Hel" },
    { type: "delta", text: "lo" },
  ]);
  const events = [];
  for await (const e of parseSSE(res.body!)) events.push(e);
  expect(events.map((e) => e.type)).toEqual(["session", "delta", "delta"]);
});

test("API errors carry code and hint", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify({ error: { code: "llm_unavailable", message: "down", hint: "start it" } }), {
      status: 503,
    }),
  );
  await expect(api.chat({ question: "x", mode: "direct", enabled_tools: [] })).rejects.toMatchObject({
    code: "llm_unavailable",
    hint: "start it",
    status: 503,
  });
});

test("network failure becomes a helpful backend_unreachable error", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));
  const err = await api.health().catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.code).toBe("backend_unreachable");
});

test("streamChat yields the done event", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(sseResponse([{ type: "done", response: response() }]));
  const events = [];
  for await (const e of api.streamChat({ question: "x", mode: "direct", enabled_tools: [] })) events.push(e);
  expect(events[0].type).toBe("done");
});
