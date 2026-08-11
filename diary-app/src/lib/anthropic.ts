import Anthropic from "@anthropic-ai/sdk";

let client: Anthropic | undefined;

function getClient(): Anthropic {
  if (!client) {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      throw new Error("ANTHROPIC_API_KEY is not set");
    }
    client = new Anthropic({ apiKey });
  }
  return client;
}

const SYSTEM_PROMPT =
  "あなたは翻訳者です。渡された日本語の日記本文を、自然な一人称視点の英語(日記らしい、堅すぎない文体)に翻訳してください。" +
  "出力は翻訳結果の英文のみとし、前置き・説明・注釈は一切含めないでください。";

export async function translateToEnglish(contentJa: string): Promise<string> {
  const anthropic = getClient();
  const message = await anthropic.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 2048,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: contentJa }],
  });

  const textBlock = message.content.find((block) => block.type === "text");
  if (!textBlock || textBlock.type !== "text") {
    throw new Error("Anthropic API returned no text content");
  }
  return textBlock.text.trim();
}
