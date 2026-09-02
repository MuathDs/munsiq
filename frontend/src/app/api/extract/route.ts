import { NextRequest } from "next/server";
import { buildMessages, MODEL_NAME, MAX_PREDICT_TOKENS } from "@/lib/munsiqModel";

const OLLAMA_CHAT_URL = "http://localhost:11434/api/chat";

export async function POST(req: NextRequest) {
  let text: unknown;
  try {
    ({ text } = await req.json());
  } catch {
    return new Response(JSON.stringify({ error: "Request body was empty or not valid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!text || typeof text !== "string") {
    return new Response(JSON.stringify({ error: "Missing 'text' field" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  let ollamaResponse: Response;
  try {
    ollamaResponse = await fetch(OLLAMA_CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL_NAME,
        messages: buildMessages(text),
        format: "json",
        stream: true,
        options: { temperature: 0.1, num_predict: MAX_PREDICT_TOKENS },
      }),
    });
  } catch {
    return new Response(
      JSON.stringify({ error: "Could not reach Ollama at localhost:11434 -- is it running?" }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  if (!ollamaResponse.ok || !ollamaResponse.body) {
    return new Response(JSON.stringify({ error: "Ollama returned no response body" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Re-stream Ollama's newline-delimited JSON chunks straight to the client
  return new Response(ollamaResponse.body, {
    headers: { "Content-Type": "application/x-ndjson" },
  });
}
