import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

// Minimal dependency-free persistence: each "table" is a JSON object on disk, keyed by id.
// Writes are atomic (write to a temp file, then rename) so a crash mid-write can't corrupt the
// file. Single Node process + single event loop means no cross-process locking is needed here —
// swap this module for a real DB (SQLite/Postgres) if this ever runs as multiple processes.
export class JsonTable<T> {
  private data: Record<string, T>;
  private readonly filePath: string;

  constructor(filePath: string) {
    this.filePath = filePath;
    mkdirSync(dirname(filePath), { recursive: true });
    this.data = existsSync(filePath) ? JSON.parse(readFileSync(filePath, "utf-8")) : {};
  }

  get(key: string): T | undefined {
    return this.data[key];
  }

  set(key: string, value: T): void {
    this.data[key] = value;
    this.persist();
  }

  delete(key: string): void {
    delete this.data[key];
    this.persist();
  }

  values(): T[] {
    return Object.values(this.data);
  }

  private persist(): void {
    const tmpPath = `${this.filePath}.tmp`;
    writeFileSync(tmpPath, JSON.stringify(this.data, null, 2));
    renameSync(tmpPath, this.filePath);
  }
}
