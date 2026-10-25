import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";

import { PublicChat } from "@/components/public-chat";
import { publicChatKey } from "@/lib/server/public-chat";

export const metadata: Metadata = { title: "Find your home" };

/**
 * The public website chat (ADR 0013, decision 11): no menu, no sign-in, works on a phone.
 * Switched off (404) unless this server has PUBLIC_CHAT_SERVER_KEY.
 */
export default async function ChatPage() {
  // Read the settings at request time, not once at build time.
  await connection();
  if (!publicChatKey()) notFound();
  const privacyUrl = process.env.PUBLIC_CHAT_PRIVACY_URL?.trim() || undefined;
  return (
    <main className="mx-auto flex h-dvh max-w-2xl flex-col bg-slate-50 px-4 py-4 sm:py-8">
      <header className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">
          Find your home
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Chat with our property assistant. An advisor will call you back.
        </p>
      </header>
      <div className="min-h-0 flex-1">
        <PublicChat privacyUrl={privacyUrl} />
      </div>
    </main>
  );
}
