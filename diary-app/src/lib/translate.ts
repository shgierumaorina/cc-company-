const MYMEMORY_ENDPOINT = "https://api.mymemory.translated.net/get";
const MAX_CHUNK_BYTES = 480;

interface MyMemoryResponse {
  responseStatus: number | string;
  responseDetails?: string;
  responseData: {
    translatedText: string;
  };
}

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
  const url = new URL(MYMEMORY_ENDPOINT);
  url.searchParams.set("q", chunk);
  url.searchParams.set("langpair", "ja|en");

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`MyMemory API request failed with status ${res.status}`);
  }

  const data = (await res.json()) as MyMemoryResponse;
  if (Number(data.responseStatus) !== 200) {
    throw new Error(data.responseDetails ?? "MyMemory translation failed");
  }

  return data.responseData.translatedText;
}

export async function translateToEnglish(contentJa: string): Promise<string> {
  const chunks = splitIntoChunks(contentJa).filter((c) => c.trim().length > 0);
  const translated: string[] = [];
  for (const chunk of chunks) {
    translated.push(await translateChunk(chunk));
  }
  return translated.join(" ").replace(/\s+/g, " ").trim();
}
