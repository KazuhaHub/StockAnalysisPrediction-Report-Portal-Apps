/** ECharts renders tooltip strings as HTML; snapshot text must not be markup. */
export function escapeHtml(text: unknown): string {
  return String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
