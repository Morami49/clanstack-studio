/* tslint:disable */
/* eslint-disable */
export class Node {
  free(): void;
  identities(): string;
  merge_preview(from: string, into: string): string;
  /**
   * Load a key from 32 random bytes (hex). Returns its public key.
   */
  key(seed_hex: string): string;
  constructor();
  fact(author: string, kind: string, body: string, rehearsal_branch: string, lane_branch: string, ts: number): string;
  tree(): string;
  view(branch: string): string;
  merge(author: string, from: string, into: string, resolutions: string, ts: number): string;
  /**
   * parent "" = new root branch; from "" = fork at the parent's current head; horizon < 0 = live.
   */
  branch(author: string, parent: string, from: string, name: string, horizon: number, ts: number): string;
  /**
   * Everything this node holds, as JSON (any transport can carry it).
   */
  export(): string;
  /**
   * Merge in another node's export. Order doesn't matter; invalid events are refused.
   */
  import(events: string): string;
  intent(author: string, branch: string, kind: string, body: string, ts: number): string;
  verify(): string;
  view_at(intent: string): string;
}

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
  readonly memory: WebAssembly.Memory;
  readonly __wbg_node_free: (a: number, b: number) => void;
  readonly node_branch: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number, j: number, k: number) => [number, number];
  readonly node_export: (a: number) => [number, number];
  readonly node_fact: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number, j: number, k: number, l: number) => [number, number];
  readonly node_identities: (a: number) => [number, number];
  readonly node_import: (a: number, b: number, c: number) => [number, number];
  readonly node_intent: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number, j: number) => [number, number];
  readonly node_key: (a: number, b: number, c: number) => [number, number];
  readonly node_merge: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number, j: number) => [number, number];
  readonly node_merge_preview: (a: number, b: number, c: number, d: number, e: number) => [number, number];
  readonly node_new: () => number;
  readonly node_tree: (a: number) => [number, number];
  readonly node_verify: (a: number) => [number, number];
  readonly node_view: (a: number, b: number, c: number) => [number, number];
  readonly node_view_at: (a: number, b: number, c: number) => [number, number];
  readonly __wbindgen_export_0: WebAssembly.Table;
  readonly __wbindgen_free: (a: number, b: number, c: number) => void;
  readonly __wbindgen_malloc: (a: number, b: number) => number;
  readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
  readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;
/**
* Instantiates the given `module`, which can either be bytes or
* a precompiled `WebAssembly.Module`.
*
* @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
*
* @returns {InitOutput}
*/
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
* If `module_or_path` is {RequestInfo} or {URL}, makes a request and
* for everything else, calls `WebAssembly.instantiate` directly.
*
* @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
*
* @returns {Promise<InitOutput>}
*/
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
