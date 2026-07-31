import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the local Layer Processor shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Layer Processor · Control Room<\/title>/i);
  assert.match(html, /Dashboard locale per orchestrare e monitorare/);
  assert.match(html, /class="loading-screen">Caricamento…<\/main>/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/i);
});

test("keeps regional process controls in the product UI", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /const runStage = async \(stage: string\)/);
  assert.match(page, /stage\.available && !isActiveJob/);
  assert.match(page, /runStage\(stage\.id\)/);
  assert.match(page, /Scoperta fonti|data\.stages/);
  assert.match(page, /batch_size: stage === "download"/);
  assert.match(page, /Mostra altre chiamate/);
  assert.match(page, /Vedi layer/);
  assert.match(page, /Output di Composizione/);
  assert.match(page, /5 stadi · 20% ciascuno/);
  assert.match(page, /pipeline_completion_pct/);
  assert.match(page, /100% = dati completi, layer creati e caricati/);
  assert.match(page, /Avanzamento medio/);
  assert.match(page, /Avanzamento per regione/);
  assert.match(page, /Apri i processi di questa regione/);
  assert.match(page, /Riprendi dal punto interrotto/);
  assert.match(page, /Seleziona mancanti/);
  assert.match(page, /Avanzamento regionale/);
  assert.match(page, /stage-collapsed/);
  assert.match(page, /Mostra chiamate e log/);
  assert.match(page, /Esecuzioni recenti/);
  assert.match(page, /Da riprendere/);
  assert.match(page, /Prima del caricamento/);
  assert.match(page, />\s*Fonti\s*</);
  assert.match(page, /Registro territoriale/);
  assert.match(page, /Tipo di piano/);
  assert.match(page, /Apri fonte/);
  assert.match(page, /Solo fonti attive/);
  assert.match(page, /sourceInstrumentFallback/);
  assert.match(layout, /Layer Processor · Control Room/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);

  await assert.rejects(
    access(new URL("../app/_sites-preview", import.meta.url)),
  );
});
