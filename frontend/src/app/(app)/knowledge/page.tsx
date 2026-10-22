import type { Metadata } from "next";

import { ActionDialog } from "@/components/action-dialog";
import { KnowledgeUploadForm } from "@/components/knowledge-form";
import {
  ButtonLink,
  Card,
  EmptyState,
  ErrorAlert,
  Forbidden,
  PageHeader,
  SuccessAlert,
  cx,
} from "@/components/ui";
import { ApiError, toErrorInfo } from "@/lib/api-error";
import type {
  KnowledgeDocument,
  KnowledgeDocumentPage,
  KnowledgeDocumentStatus,
} from "@/lib/api-types";
import { initialDialogState } from "@/lib/dialog-state";
import { canManageKnowledge, canReadKnowledge } from "@/lib/permissions";
import { apiFetch, getMe } from "@/lib/server/api";

import { deleteKnowledge, uploadKnowledge } from "./actions";

export const metadata: Metadata = { title: "Knowledge" };

const STATUS: Record<
  KnowledgeDocumentStatus,
  { label: string; badge: string; help: string }
> = {
  processing: {
    label: "Processing",
    badge: "bg-amber-50 text-amber-800 ring-amber-200",
    help: "The worker is reading the file. Refresh in a moment.",
  },
  indexed: {
    label: "Indexed",
    badge: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    help: "Text extracted and split into chunks, ready for search.",
  },
  needs_review: {
    label: "Needs review",
    badge: "bg-orange-50 text-orange-800 ring-orange-200",
    help: "Personal data was found. Redact the file and upload it again - it is not indexed.",
  },
  no_text: {
    label: "No readable text",
    badge: "bg-slate-100 text-slate-700 ring-slate-300",
    help: "Scanned PDFs have no text layer; OCR is not available yet.",
  },
  failed: {
    label: "Failed",
    badge: "bg-red-50 text-red-800 ring-red-200",
    help: "Indexing failed. Check the file and upload it again.",
  },
};

function fileSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function createdLabel(document: KnowledgeDocument): string {
  return new Date(document.created_at).toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default async function KnowledgePage({
  searchParams,
}: PageProps<"/knowledge">) {
  const raw = await searchParams;
  const one = (value: string | string[] | undefined) =>
    (Array.isArray(value) ? value[0] : value) ?? "";
  const done = one(raw.done);

  const me = await getMe();
  if (!canReadKnowledge(me)) return <Forbidden />;
  const manager = canManageKnowledge(me);

  let data: KnowledgeDocumentPage | null = null;
  let failure = null;
  try {
    data = await apiFetch<KnowledgeDocumentPage>("/knowledge/documents?limit=100");
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return <Forbidden />;
    failure = toErrorInfo(error);
  }

  return (
    <>
      <PageHeader
        title="Knowledge"
        description="Company policies and manuals become searchable passages, with citations. Uploads are indexed in the background."
        actions={
          <ButtonLink href="/knowledge/search">Search &amp; ask</ButtonLink>
        }
      />
      {done === "uploaded" && (
        <div className="mb-5">
          <SuccessAlert>
            Uploaded. The status below becomes <strong>Indexed</strong> when the worker is done.
          </SuccessAlert>
        </div>
      )}
      {done === "deleted" && (
        <div className="mb-5">
          <SuccessAlert>Deleted the document, its chunks and the stored file.</SuccessAlert>
        </div>
      )}
      {failure && <ErrorAlert title="Knowledge could not be loaded" error={failure} />}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          {!data || data.items.length === 0 ? (
            <EmptyState
              title="No knowledge documents yet"
              description={
                manager
                  ? "Upload a policy or manual on the right; it is split into passages automatically."
                  : "Ask a tenant admin to upload a policy or manual."
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <caption className="sr-only">Knowledge documents and indexing status</caption>
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3">Document</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="px-5 py-3 text-right">Pages</th>
                    <th scope="col" className="px-5 py-3 text-right">Chunks</th>
                    <th scope="col" className="px-5 py-3">Uploaded</th>
                    {manager && <th scope="col" className="px-5 py-3 text-right">Actions</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {data.items.map((document) => {
                    const status = STATUS[document.status];
                    return (
                      <tr key={document.id}>
                        <td className="px-5 py-3">
                          <p className="font-medium text-slate-900">{document.title}</p>
                          <p className="text-xs text-slate-500">
                            {document.file_name} · {fileSize(document.size_bytes)} ·{" "}
                            {document.visibility === "customer_visible"
                              ? "Customer-visible"
                              : "Internal"}
                          </p>
                        </td>
                        <td className="px-5 py-3">
                          <span
                            title={status.help}
                            className={cx(
                              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
                              status.badge,
                            )}
                          >
                            {status.label}
                          </span>
                          {document.status === "needs_review" && document.error && (
                            <p className="mt-1 text-xs text-orange-700">
                              Found: {document.error.replace("personal_data:", "").replaceAll(",", ", ")}
                            </p>
                          )}
                        </td>
                        <td className="px-5 py-3 text-right tabular-nums">{document.page_count}</td>
                        <td className="px-5 py-3 text-right tabular-nums">{document.chunk_count}</td>
                        <td className="px-5 py-3 text-slate-600">{createdLabel(document)}</td>
                        {manager && (
                          <td className="px-5 py-3 text-right">
                            <ActionDialog
                              triggerLabel="Delete"
                              triggerVariant="danger"
                              title={"Delete " + document.title + "?"}
                              description="The document, all of its chunks and the stored file are removed. This cannot be undone."
                              confirmLabel="Delete"
                              confirmVariant="danger"
                              action={deleteKnowledge.bind(null, document.id)}
                              initialState={initialDialogState}
                            />
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="space-y-6">
          {manager && (
            <Card className="p-5">
              <h2 className="text-base font-semibold text-slate-900">Upload a document</h2>
              <p className="mt-1 mb-4 text-sm text-slate-600">
                PDF, Word, TXT or Markdown, up to 20 MB. Personal data is detected before
                indexing, and scanned PDFs are refused until OCR exists.
              </p>
              <KnowledgeUploadForm action={uploadKnowledge} />
            </Card>
          )}
          <Card className="p-5 text-sm">
            <h2 className="text-base font-semibold text-slate-900">How statuses work</h2>
            <ul className="mt-2 space-y-2 text-slate-600">
              <li><strong>Processing</strong> - waiting for the worker.</li>
              <li><strong>Indexed</strong> - text extracted, checked and split into chunks.</li>
              <li><strong>Needs review</strong> - possible personal data; nothing was indexed.</li>
              <li><strong>No readable text</strong> - scanned image PDF; OCR is a later step.</li>
              <li><strong>Failed</strong> - the file could not be read; upload it again.</li>
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
