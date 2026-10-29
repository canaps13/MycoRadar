export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api" || pathname.startsWith("/api/")) {
      return new Response(
        JSON.stringify({ status: "unavailable", reason: "backend_not_deployed" }),
        {
          status: 503,
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
          },
        },
      );
    }
    return env.ASSETS.fetch(request);
  },
};
