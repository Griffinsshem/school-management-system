import { expect, test } from "@playwright/test";

// The API accepts requests only through this website (src/proxy.ts adds a
// secret shared with the API), and counts failed logins per visitor using
// the address this website passes on. See backend/app/frontend_proxy.py.
const API_DIRECT = "http://127.0.0.1:5001";

test("the API refuses requests that do not come through the website", async ({ request }) => {
  expect((await request.get(`${API_DIRECT}/api/v1/auth/me`)).status()).toBe(403);
  const guess = { "X-SMS-Proxy-Secret": "a guess" };
  expect((await request.get(`${API_DIRECT}/api/v1/auth/me`, { headers: guess })).status()).toBe(403);
  // The host's health checks still work without the secret.
  expect((await request.get(`${API_DIRECT}/api/v1/health`)).status()).toBe(200);

  // Through the website the same request reaches the API: not logged in.
  expect((await request.get("/api/v1/auth/me", { headers: guess })).status()).toBe(401);
});

test("failed logins are counted per visitor, and a forged visitor address is ignored", async ({
  request,
}) => {
  // Addresses from the documentation-only range, different on every run.
  const run = Date.now().toString(16);
  const visitor = `2001:db8:${run.slice(-4)}::1`;
  const otherVisitor = `2001:db8:${run.slice(-4)}::2`;

  async function failLogin(from: string, number: number) {
    const response = await request.post("/api/v1/auth/login", {
      // The visitor also tries to choose the address the API should count.
      headers: { "X-Forwarded-For": from, "X-SMS-Client-IP": `2001:db8:ffff::${number}` },
      data: { email: `nobody.${run}.${number}@example.com`, password: "not the right password" },
    });
    return response.status();
  }

  for (let number = 1; number <= 50; number++) {
    expect(await failLogin(visitor, number)).toBe(401);
  }
  // The 51st failure from the same visitor is refused, although the forged
  // X-SMS-Client-IP changed every time; another visitor is not affected.
  expect(await failLogin(visitor, 51)).toBe(429);
  expect(await failLogin(otherVisitor, 52)).toBe(401);
});
