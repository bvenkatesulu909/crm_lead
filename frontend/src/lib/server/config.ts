import "server-only";

import { z } from "zod";

/**
 * Server configuration, read from environment variables (.env.local in development).
 * Validated once at startup: a missing or malformed value stops the app with a clear message
 * instead of failing later during a login. Nothing here is ever sent to the browser.
 */
const schema = z.object({
  APP_BASE_URL: z.url(),
  API_BASE_URL: z.url(),
  OIDC_ISSUER: z.url(),
  OIDC_CLIENT_ID: z.string().min(1),
  OIDC_CLIENT_SECRET: z.string().min(16, "OIDC_CLIENT_SECRET looks too short"),
  // 32 random bytes, base64url-encoded (43 characters).
  SESSION_SECRET: z
    .string()
    .regex(/^[A-Za-z0-9_-]{43}$/, "SESSION_SECRET must be 32 bytes, base64url"),
});

export type ServerConfig = z.infer<typeof schema> & { secureCookies: boolean };

let cached: ServerConfig | undefined;

export function serverConfig(): ServerConfig {
  if (!cached) {
    const parsed = schema.safeParse(process.env);
    if (!parsed.success) {
      const problems = parsed.error.issues.map(
        (i) => `${i.path.join(".")}: ${i.message}`,
      );
      throw new Error(
        `Invalid web app configuration (see .env.example):\n${problems.join("\n")}`,
      );
    }
    cached = {
      ...parsed.data,
      // Secure cookies need HTTPS. Plain http://localhost is only acceptable in development.
      secureCookies: parsed.data.APP_BASE_URL.startsWith("https://"),
    };
  }
  return cached;
}
