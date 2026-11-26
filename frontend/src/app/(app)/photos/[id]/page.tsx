import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PhotoCopies } from "@/components/photo-copies";
import { PhotoWorkbench } from "@/components/photo-workbench";
import { Forbidden, PageHeader, SuccessAlert } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { DocumentList } from "@/lib/api-types";
import { canEnhancePhotos } from "@/lib/permissions";
import { isPhoto, type EnhancementPage } from "@/lib/photo-enhancer";
import { apiFetch, getMe } from "@/lib/server/api";

export const metadata: Metadata = { title: "Adjust a photo" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DONE: Record<string, string> = {
  queued: "The adjusted copy is being made. It appears below in a moment.",
  deleted: "The adjusted copy was deleted. Your original photo is untouched.",
};

/**
 * Adjust one property photo (ADR 0039). Only a JPEG or PNG attached to an account or deal that the
 * person may see; the API answers 404 otherwise (then this page says "not found"). People without
 * the permission see an explanation, never the tool.
 */
export default async function PhotoPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ done?: string }>;
}) {
  const { id } = await params;
  const { done } = await searchParams;
  if (!UUID.test(id)) notFound();
  const me = await getMe();
  if (!canEnhancePhotos(me))
    return <Forbidden message="You are not allowed to adjust photos." />;

  const versions = await apiFetch<DocumentList>(
    `/documents/${id}/versions`,
  ).catch((error) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  });
  const photo = versions.items.find((item) => item.id === id);
  if (!photo || !isPhoto(photo.content_type)) notFound();
  const copies = await apiFetch<EnhancementPage>(
    `/photo-enhancer/enhancements?document_id=${id}`,
  ).catch(() => ({ items: [], caption: "" }) as EnhancementPage);
  const back =
    photo.record_type === "account"
      ? `/accounts/${photo.record_id}`
      : `/opportunities/${photo.record_id}`;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Adjust a photo"
        description={photo.file_name}
        actions={
          <Link href={back} className="text-sm text-brand-700 hover:underline">
            Back to the record
          </Link>
        }
      />
      {done && DONE[done] && <SuccessAlert>{DONE[done]}</SuccessAlert>}
      <PhotoWorkbench documentId={id} fileName={photo.file_name} />
      <section aria-labelledby="copies-heading" className="space-y-3">
        <h2
          id="copies-heading"
          className="text-base font-semibold text-slate-900"
        >
          Adjusted copies
        </h2>
        <PhotoCopies
          documentId={id}
          copies={copies.items}
          caption={copies.caption}
          canDelete
        />
      </section>
    </div>
  );
}
