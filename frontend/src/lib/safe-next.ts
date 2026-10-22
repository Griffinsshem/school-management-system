// Where to go after logging in. Only paths on this site are allowed, so a
// link such as /login?next=https://evil.example cannot send people elsewhere.
const BASE = "http://this-site.invalid";

export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  try {
    const url = new URL(value, BASE);
    if (url.origin !== BASE) {
      return "/";
    }
    return `${url.pathname}${url.search}`;
  } catch {
    return "/";
  }
}
