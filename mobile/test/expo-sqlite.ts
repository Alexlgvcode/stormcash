// Test double for expo-sqlite's synchronous API, backed by node:sqlite (in-memory).
import { DatabaseSync } from 'node:sqlite';

type Params = unknown[];
const flat = (p: Params): any[] => (p.length === 1 && Array.isArray(p[0]) ? (p[0] as any[]) : (p as any[]));

class Db {
  private d = new DatabaseSync(':memory:');
  execSync(sql: string) { this.d.exec(sql.replace(/PRAGMA journal_mode = WAL;/, '')); }
  runSync(sql: string, ...p: Params) {
    const r = this.d.prepare(sql).run(...flat(p));
    return { changes: Number(r.changes), lastInsertRowId: Number(r.lastInsertRowid) };
  }
  getFirstSync<T>(sql: string, ...p: Params): T | null { return (this.d.prepare(sql).get(...flat(p)) as T) ?? null; }
  getAllSync<T>(sql: string, ...p: Params): T[] { return this.d.prepare(sql).all(...flat(p)) as T[]; }
  withTransactionSync(task: () => void) {
    this.d.exec('BEGIN');
    try { task(); this.d.exec('COMMIT'); } catch (e) { this.d.exec('ROLLBACK'); throw e; }
  }
}

export type SQLiteDatabase = Db;
const open = new Map<string, Db>();
export const openDatabaseSync = (name: string): Db => {
  if (!open.has(name)) open.set(name, new Db());
  return open.get(name)!;
};
