// TrendSpider webhook receiver → ic_technical_alerts
// Auth: shared secret in ?token= (TrendSpider cannot set custom auth headers).
// See TRENDSPIDER_INTEGRATION.md.
import { createClient } from "jsr:@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const url = new URL(req.url);
  if (url.searchParams.get("token") !== Deno.env.get("TS_WEBHOOK_SECRET")) {
    return new Response("forbidden", { status: 403 });
  }
  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch {
    try { body = { raw: await req.text() }; } catch { /* empty body */ }
  }
  const db = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );
  const { error } = await db.from("ic_technical_alerts").insert({
    ticker: String(body.ticker ?? "").toUpperCase() || null,
    alert_name: (body.alert_name as string) ?? null,
    signal: (body.signal as string) ?? null,
    price: Number(body.price) || null,
    payload: body,
  });
  return new Response(error ? `db error: ${error.message}` : "ok",
                      { status: error ? 500 : 200 });
});
