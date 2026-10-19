import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center p-6 text-center">
      <div>
        <p className="text-sm font-semibold text-brand-700">404</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-900">
          Page not found
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          The page doesn&apos;t exist or has moved.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline"
        >
          Back to the dashboard
        </Link>
      </div>
    </main>
  );
}
