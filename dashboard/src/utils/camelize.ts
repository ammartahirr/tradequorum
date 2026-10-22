/** Backend (Python) sends snake_case keys; the dashboard types are camelCase. */
export function camelizeKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelizeKeys);
  if (value && typeof value === 'object' && (value as object).constructor === Object) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase()),
        camelizeKeys(v),
      ]),
    );
  }
  return value;
}
