/**
 * Where to send the user after login. Only paths on THIS site are allowed, so a crafted link
 * like /login?returnTo=https://evil.example cannot turn our login into an open redirect.
 */
export function safeReturnTo(value: string | null | undefined): string {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\")
  ) {
    return "/";
  }
  // Control characters could smuggle a different URL through some parsers.
  if (/[\u0000-\u001f]/.test(value)) return "/";
  if (value.startsWith("/api/auth/") || value.startsWith("/login")) return "/";
  return value;
}
