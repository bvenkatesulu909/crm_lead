import {
  deleteDocument,
  uploadDocument,
  type RecordType,
} from "@/app/(app)/documents/actions";
import {
  DeleteDocumentDialog,
  UploadDocumentDialog,
} from "@/components/document-dialogs";
import { Card } from "@/components/ui";
import type { DocumentItem, DocumentList, Me } from "@/lib/api-types";
import { formatBytes, formatDateTime } from "@/lib/format";
import {
  canDeleteDocuments,
  canReadDocuments,
  canWriteDocuments,
} from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/** Older versions are loaded only for documents that have them (usually few). */
async function olderVersions(doc: DocumentItem): Promise<DocumentItem[]> {
  if (doc.versions < 2) return [];
  return apiFetch<DocumentList>(`/documents/${doc.id}/versions`)
    .then((v) => v.items.filter((x) => x.id !== doc.id))
    .catch(() => []);
}

/**
 * Documents of an account or deal. The list comes from the API, which shows documents only
 * to people who may see the record; downloads go through /documents/<id>/download.
 */
export async function DocumentsCard({
  me,
  recordType,
  recordId,
}: {
  me: Me;
  recordType: RecordType;
  recordId: string;
}) {
  if (!canReadDocuments(me)) return null;
  const params = new URLSearchParams({
    record_type: recordType,
    record_id: recordId,
  });
  const list = await apiFetch<DocumentList>(`/documents?${params}`).catch(
    () => null,
  );
  if (!list) return null;
  const older = await Promise.all(list.items.map(olderVersions));
  const mayDelete = canDeleteDocuments(me);

  return (
    <Card aria-labelledby={`documents-${recordId}`}>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <h2 id={`documents-${recordId}`} className="text-base font-semibold text-slate-900">Documents</h2>
        {canWriteDocuments(me) && (
          <UploadDocumentDialog action={uploadDocument.bind(null, recordType, recordId)} allowCustomerVisible={recordType === "account"} />
        )}
      </div>
      {list.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-600">No documents yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {list.items.map((d, i) => (
            <li key={d.id} className="px-5 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <a href={`/documents/${d.id}/download`} download className="break-all text-sm font-medium text-brand-700 hover:underline">{d.file_name}</a>
                  <p className="text-xs text-slate-500">
                    {d.version_no > 1 && `Version ${d.version_no} · `}{formatBytes(d.size_bytes)} · {formatDateTime(d.created_at)}{d.created_by_name && ` · ${d.created_by_name}`}
                  </p>
                  {d.description && <p className="mt-0.5 text-xs text-slate-600">{d.description}</p>}
                  {d.customer_visible && <span className="mt-1 inline-block rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800">Visible to the customer</span>}
                </div>
                {mayDelete && (
                  <DeleteDocumentDialog action={deleteDocument.bind(null, recordType, recordId, d.id)} name={d.file_name} versions={d.versions} />
                )}
              </div>
              {older[i].length > 0 && (
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer text-slate-600">Older versions ({older[i].length})</summary>
                  <ul className="mt-1 space-y-1 pl-4">
                    {older[i].map((v) => (
                      <li key={v.id}>
                        <a href={`/documents/${v.id}/download`} download className="text-brand-700 hover:underline">Version {v.version_no}</a>
                        <span className="text-slate-500"> · {formatBytes(v.size_bytes)} · {formatDateTime(v.created_at)}{v.created_by_name && ` · ${v.created_by_name}`}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  ); // prettier-ignore
}
