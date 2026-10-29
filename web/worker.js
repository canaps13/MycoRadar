export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api" || pathname.startsWith("/api/")) {
      const body = JSON.stringify({
        status: "unavailable",
        reason: "backend_not_deployed",
      });
      return new Response(body, {
        status: 503,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        },
      });
    }
    return env.ASSETS.fetch(request);
  },
};
