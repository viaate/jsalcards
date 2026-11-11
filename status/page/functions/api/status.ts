/**
 * GET /api/status: the checker's summary as it is in the store, with this server's clock. It
 * reads nothing of the request, logs nothing and sets no cookie. It is never answered from a
 * cache: an answer kept for a while would carry an old `served`, and the page, which counts
 * from `served`, would read its clock as that much behind.
 */

interface Env {
  DB: D1Database;
}

const JSON_TYPE = 'application/json; charset=utf-8';

export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  let summary: string;
  try {
    const row = await env.DB.prepare("SELECT v FROM meta WHERE k = 'summary'").first<{
      v: string;
    }>();
    summary = row === null ? 'null' : row.v;
  } catch {
    return new Response('{"error":"store"}', {
      status: 503,
      headers: {
        'content-type': JSON_TYPE,
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
      },
    });
  }
  const served = Math.floor(Date.now() / 1000);
  return new Response(`{"served":${served},"summary":${summary}}`, {
    status: 200,
    headers: {
      'content-type': JSON_TYPE,
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
    },
  });
};

/** Every other method. */
export const onRequest: PagesFunction<Env> = () =>
  new Response(null, { status: 405, headers: { allow: 'GET' } });
