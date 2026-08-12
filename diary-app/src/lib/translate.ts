function endpointFor(apiKey: string): string {
  return apiKey.endsWith(":fx")
    ? "https://api-free.deepl.com/v2/translate"
    : "https://api.deepl.com/v2/translate";
}

export async function translateToEnglish(contentJa: string): Promise<string> {
  const apiKey = process.env.DEEPL_API_KEY;
  if (!apiKey) {
    throw new Error("DEEPL_API_KEY is not set");
  }

  const res = await fetch(endpointFor(apiKey), {
    method: "POST",
    headers: {
      Authorization: `DeepL-Auth-Key ${apiKey}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      text: contentJa,
      source_lang: "JA",
      target_lang: "EN-US",
    }),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `DeepL API request failed with status ${res.status}${detail ? `: ${detail}` : ""}`
    );
  }

  const data = (await res.json()) as { translations?: { text: string }[] };
  const translation = data.translations?.[0]?.text;
  if (!translation) {
    throw new Error("DeepL API returned no translation");
  }
  return translation;
}
