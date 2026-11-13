import {
  deleteCallAudio,
  finishCallUpload,
  listenToCall,
  readCallTranscript,
  startCallUpload,
} from "@/app/(app)/leads/[id]/call-actions";
import { CallsView } from "@/components/calls-views";
import { Card } from "@/components/ui";
import type { Me } from "@/lib/api-types";
import type { CallRecording } from "@/lib/calls";
import { canReadCalls, canWriteCalls } from "@/lib/permissions";
import { apiFetch } from "@/lib/server/api";

/**
 * Call recordings of this lead (ADR 0030). Information only - the lead page works without it - and
 * the API answers 404 when the person may not read the lead, then nothing is shown.
 */
export async function CallsCard({
  me,
  leadId,
}: {
  me: Pick<Me, "permissions">;
  leadId: string;
}) {
  if (!canReadCalls(me)) return null;
  const data = await apiFetch<{ items: CallRecording[] }>(
    `/leads/${leadId}/calls`,
  ).catch(() => null);
  if (!data) return null;
  return (
    <Card id="calls" aria-labelledby="calls-heading" className="p-5">
      <h2 id="calls-heading" className="text-base font-semibold text-slate-900">
        Call recordings
      </h2>
      <div className="mt-3">
        <CallsView
          calls={data.items}
          canWrite={canWriteCalls(me)}
          actions={{
            start: startCallUpload.bind(null, leadId),
            finish: finishCallUpload.bind(null, leadId),
            deleteAudio: deleteCallAudio.bind(null, leadId),
            listen: listenToCall.bind(null, leadId),
            read: readCallTranscript.bind(null, leadId),
          }}
        />
      </div>
    </Card>
  );
}
