import type { components } from "./schema";

type S = components["schemas"];

export type Me = S["Me"];
export type StatusOut = S["StatusOut"];
export type TaskView = S["TaskView"];
export type GroupNode = S["GroupNode"];
export type DocumentOut = S["DocumentOut"];
export type DocumentDetailOut = S["DocumentDetailOut"];
export type PersonProgress = S["PersonProgress"];
export type TurnOut = S["TurnOut"];
export type TurnCitation = S["TurnCitation"];
export type Citation = S["Citation"];
export type DoneEvent = S["DoneEvent"];
export type ClosestDoc = S["ClosestDoc"];
export type NewTask = S["NewTask"];
export type TaskPatch = S["TaskPatch"];
export type DocumentPatch = S["DocumentPatch"];
export type NewGroup = S["NewGroup"];
export type LinkBody = S["LinkBody"];

export type DocStatus = DocumentOut["status"];
export type DocType = DocumentOut["doc_type"];
export type GroupKind = GroupNode["kind"];
