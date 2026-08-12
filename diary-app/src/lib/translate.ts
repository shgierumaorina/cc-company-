const GOOGLE_TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single";
const MAX_CHUNK_BYTES = 4000;

function utf8ByteLength(str: string): number {
  return new TextEncoder().encode(str).length;
}

function splitIntoChunks(text: string): string[] {
  const sentences = text.split(/(?<=[。！？\n])/);
  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    if (current && utf8ByteLength(current + sentence) > MAX_CHUNK_BYTES) {
      chunks.push(current);
      current = sentence;
    } else {
      current += sentence;
    }
  }
  if (current) chunks.push(current);
  return chunks.length > 0 ? chunks : [text];
}

async function translateChunk(chunk: string): Promise<string> {
  const url = new URL(GOOGLE_TRANSLATE_ENDPOINT);
  url.searchParams.set("client", "gtx");
  url.searchParams.set("sl", "ja");
  url.searchParams.set("tl", "en");
  url.searchParams.set("dt", "t");
  url.searchParams.set("q", chunk);

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`Google Translate request failed with status ${res.status}`);
  }

  const data = (await res.json()) as unknown;
  const segments = Array.isArray(data) ? (data[0] as unknown) : undefined;
  if (!Array.isArray(segments)) {
    throw new Error("Unexpected Google Translate response shape");
  }

  return segments
    .map((segment) => (Array.isArray(segment) ? String(segment[0] ?? "") : ""))
    .join("");
}

export async function translateToEnglish(contentJa: string): Promise<string> {
  const chunks = splitIntoChunks(contentJa).filter((c) => c.trim().length > 0);
  const translated: string[] = [];
  for (const chunk of chunks) {
    translated.push(await translateChunk(chunk));
  }
  return translated.join(" ").replace(/\s+/g, " ").trim();
}
