"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { DialogField } from "@/components/action-dialog";
import { ErrorAlert, buttonClass, cx } from "@/components/ui";
import type {
  CatalogueField,
  RuleAction,
  RuleCondition,
  WorkflowCatalogue,
  WorkflowRule,
} from "@/lib/api-types";
import type { FormState } from "@/lib/form-state";
import { OPERATOR_LABELS, ROLE_NAMES, optionLabel } from "@/lib/workflows";

type Person = { id: string; name: string };

const box =
  "rounded-md border-0 px-2 py-1.5 text-sm ring-1 ring-inset ring-slate-300";

function parse<T>(json: string | undefined, fallback: T): T {
  try {
    return json ? (JSON.parse(json) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** Create or edit an automation rule: trigger -> conditions -> actions. */
export function RuleForm({
  action,
  initialState,
  catalogue,
  colleagues,
  rule,
  submitLabel,
}: {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  initialState: FormState;
  catalogue: WorkflowCatalogue;
  colleagues: Person[];
  rule?: WorkflowRule;
  submitLabel: string;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const v = state.values;
  const [triggerKey, setTriggerKey] = useState(
    v.trigger ?? rule?.trigger ?? catalogue.triggers[0].key,
  );
  const [conditions, setConditions] = useState<RuleCondition[]>(
    parse(v.conditions_json, rule?.conditions ?? []),
  );
  const [actions, setActions] = useState<RuleAction[]>(
    parse(
      v.actions_json,
      rule?.actions ?? [
        {
          type: "create_task",
          subject: "Follow up {record}",
          due_in_days: 1,
          assignee: "owner",
        },
      ],
    ),
  );
  const trigger =
    catalogue.triggers.find((t) => t.key === triggerKey) ??
    catalogue.triggers[0];
  const fieldOf = (key: string): CatalogueField | undefined =>
    trigger.fields.find((f) => f.key === key);

  const changeTrigger = (key: string) => {
    const next = catalogue.triggers.find((t) => t.key === key);
    setTriggerKey(key);
    setConditions([]); // fields differ per trigger
    setActions(
      actions.filter(
        (a) =>
          a.type !== "update_field" ||
          next?.field_updates.some((u) => u.key === a.field),
      ),
    );
  };
  const setCondition = (i: number, change: Partial<RuleCondition>) =>
    setConditions(
      conditions.map((c, j) => (j === i ? { ...c, ...change } : c)),
    );
  const setAction = (i: number, next: RuleAction) =>
    setActions(actions.map((a, j) => (j === i ? next : a)));
  const newAction = (type: RuleAction["type"]): RuleAction =>
    type === "create_task"
      ? {
          type,
          subject: "Follow up {record}",
          due_in_days: 1,
          assignee: "owner",
        }
      : type === "notify"
        ? { type, message: "Please have a look", to: "owner" }
        : {
            type,
            field: trigger.field_updates[0]?.key ?? "",
            value: trigger.field_updates[0]?.options[0] ?? "",
          };

  const people = (withRoles: boolean) => (
    <>
      <option value="owner">The record&apos;s owner</option>
      {withRoles &&
        catalogue.roles.map((r) => (
          <option key={r} value={`role:${r}`}>
            Everyone who is {ROLE_NAMES[r] ?? r}
          </option>
        ))}
      {colleagues.map((p) => (
        <option key={p.id} value={`user:${p.id}`}>
          {p.name}
        </option>
      ))}
    </>
  );

  return (
    <form key={state.attempt} action={formAction} noValidate className="space-y-6">
      {state.error && <ErrorAlert title="The rule could not be saved" error={state.error} />}
      <div className="grid gap-5 sm:grid-cols-2">
        <DialogField id="rule-name" label="Name" error={state.fieldErrors.name}>
          {(p) => <input name="name" maxLength={100} defaultValue={v.name ?? rule?.name} {...p} />}
        </DialogField>
        <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
          <input type="checkbox" name="is_active" defaultChecked={v.is_active ? v.is_active === "on" : rule?.is_active ?? true} className="h-4 w-4 rounded border-slate-300 text-brand-600" />
          Active
        </label>
        <DialogField id="rule-trigger" label="When…">
          {(p) => (
            <select name="trigger" value={triggerKey} onChange={(e) => changeTrigger(e.target.value)} {...p}>
              {catalogue.triggers.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          )}
        </DialogField>
        {trigger.kind === "schedule" && (
          <DialogField id="rule-days" label={trigger.days_label ?? "Days"} hint="0 to 365">
            {(p) => <input name="days" type="number" min={0} max={365} defaultValue={v.days ?? rule?.days ?? 3} {...p} />}
          </DialogField>
        )}
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-slate-900">…and these conditions are true (all of them)</legend>
        {conditions.length === 0 && <p className="mb-2 text-sm text-slate-500">No conditions: the rule acts every time.</p>}
        <ul className="space-y-2">
          {conditions.map((c, i) => {
            const field = fieldOf(c.field);
            const ops = field ? catalogue.operators[field.type] ?? [] : [];
            return (
              <li key={i} className="flex flex-wrap items-center gap-2" aria-label={`Condition ${i + 1}`}>
                <select aria-label={`Condition ${i + 1} field`} value={c.field} className={box}
                  onChange={(e) => { const f = fieldOf(e.target.value); setCondition(i, { field: e.target.value, op: catalogue.operators[f?.type ?? "text"]?.[0] ?? "eq", value: f?.options[0] ?? "" }); }}>
                  {trigger.fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                </select>
                <select aria-label={`Condition ${i + 1} comparison`} value={c.op} className={box}
                  onChange={(e) => setCondition(i, { op: e.target.value, value: e.target.value === "in" ? [] : field?.options[0] ?? "" })}>
                  {ops.map((op) => <option key={op} value={op}>{OPERATOR_LABELS[op] ?? op}</option>)}
                </select>
                {field?.type === "choice" && c.op === "in" ? (
                  <select multiple aria-label={`Condition ${i + 1} values`} value={Array.isArray(c.value) ? c.value : []} className={cx(box, "h-24")}
                    onChange={(e) => setCondition(i, { value: Array.from(e.target.selectedOptions, (o) => o.value) })}>
                    {field.options.map((o) => <option key={o} value={o}>{optionLabel(o)}</option>)}
                  </select>
                ) : field?.type === "choice" ? (
                  <select aria-label={`Condition ${i + 1} value`} value={String(c.value)} className={box} onChange={(e) => setCondition(i, { value: e.target.value })}>
                    {field.options.map((o) => <option key={o} value={o}>{optionLabel(o)}</option>)}
                  </select>
                ) : (
                  <input aria-label={`Condition ${i + 1} value`} value={String(c.value)} inputMode={field?.type === "number" ? "decimal" : undefined}
                    className={cx(box, "w-36")} onChange={(e) => setCondition(i, { value: e.target.value })} />
                )}
                <button type="button" className="text-sm text-red-700 hover:underline" onClick={() => setConditions(conditions.filter((_, j) => j !== i))}>
                  Remove<span className="sr-only"> condition {i + 1}</span>
                </button>
              </li>
            );
          })}
        </ul>
        {conditions.length < catalogue.max_conditions && trigger.fields.length > 0 && (
          <button type="button" className={cx(buttonClass("secondary"), "mt-2")}
            onClick={() => { const f = trigger.fields[0]; setConditions([...conditions, { field: f.key, op: catalogue.operators[f.type]?.[0] ?? "eq", value: f.options[0] ?? "" }]); }}>
            Add condition
          </button>
        )}
        <input type="hidden" name="conditions_json" value={JSON.stringify(conditions)} />
      </fieldset>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-slate-900">…then do this</legend>
        <ul className="space-y-3">
          {actions.map((a, i) => (
            <li key={i} className="space-y-2 rounded-md p-3 ring-1 ring-slate-200" aria-label={`Action ${i + 1}`}>
              <div className="flex flex-wrap items-center gap-2">
                <select aria-label={`Action ${i + 1} type`} value={a.type} className={box} onChange={(e) => setAction(i, newAction(e.target.value as RuleAction["type"]))}>
                  <option value="create_task">Create a task</option>
                  <option value="notify">Send a notification</option>
                  {trigger.field_updates.length > 0 && <option value="update_field">Change a field</option>}
                </select>
                <button type="button" className="text-sm text-red-700 hover:underline" onClick={() => setActions(actions.filter((_, j) => j !== i))}>
                  Remove<span className="sr-only"> action {i + 1}</span>
                </button>
              </div>
              {a.type === "create_task" && (
                <div className="flex flex-wrap gap-2">
                  <input aria-label={`Action ${i + 1} task subject`} value={a.subject} maxLength={200} className={cx(box, "w-72")} onChange={(e) => setAction(i, { ...a, subject: e.target.value })} />
                  <label className="flex items-center gap-1 text-sm text-slate-700">due in
                    <input aria-label={`Action ${i + 1} due in days`} type="number" min={0} max={365} value={a.due_in_days} className={cx(box, "w-20")}
                      onChange={(e) => setAction(i, { ...a, due_in_days: Number(e.target.value) })} /> days, for
                  </label>
                  <select aria-label={`Action ${i + 1} assignee`} value={a.assignee} className={box} onChange={(e) => setAction(i, { ...a, assignee: e.target.value })}>{people(false)}</select>
                </div>
              )}
              {a.type === "notify" && (
                <div className="flex flex-wrap gap-2">
                  <input aria-label={`Action ${i + 1} message`} value={a.message} maxLength={200} className={cx(box, "w-72")} onChange={(e) => setAction(i, { ...a, message: e.target.value })} />
                  <select aria-label={`Action ${i + 1} recipients`} value={a.to} className={box} onChange={(e) => setAction(i, { ...a, to: e.target.value })}>{people(true)}</select>
                </div>
              )}
              {a.type === "update_field" && (
                <div className="flex flex-wrap gap-2">
                  <select aria-label={`Action ${i + 1} field`} value={a.field} className={box}
                    onChange={(e) => setAction(i, { ...a, field: e.target.value, value: trigger.field_updates.find((u) => u.key === e.target.value)?.options[0] ?? "" })}>
                    {trigger.field_updates.map((u) => <option key={u.key} value={u.key}>{u.label}</option>)}
                  </select>
                  <select aria-label={`Action ${i + 1} new value`} value={a.value} className={box} onChange={(e) => setAction(i, { ...a, value: e.target.value })}>
                    {(trigger.field_updates.find((u) => u.key === a.field)?.options ?? []).map((o) => <option key={o} value={o}>{optionLabel(o)}</option>)}
                  </select>
                </div>
              )}
            </li>
          ))}
        </ul>
        {actions.length < catalogue.max_actions && (
          <button type="button" className={cx(buttonClass("secondary"), "mt-2")} onClick={() => setActions([...actions, newAction("create_task")])}>Add action</button>
        )}
        <p className="mt-2 text-xs text-slate-500">&ldquo;{"{record}"}&rdquo; in a task subject is replaced by the record&apos;s name, e.g. &ldquo;QT-0007: 50 widgets&rdquo;.</p>
        <input type="hidden" name="actions_json" value={JSON.stringify(actions)} />
      </fieldset>

      <div className="flex justify-end gap-3 border-t border-slate-200 pt-5">
        <Link href="/automation" className={buttonClass("secondary")}>Cancel</Link>
        <button type="submit" disabled={pending} className={buttonClass("primary")}>{pending ? "Saving…" : submitLabel}</button>
      </div>
    </form>
  ); // prettier-ignore
}
