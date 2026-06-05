/** Доступ к внутренним страницам (Чанки, Справочник, админ Draft) — только этот аккаунт. */
export const INTERNAL_DEV_TOOLS_EMAIL = 'semenandronov2004@mail.ru'

export function canAccessInternalDevTools(email: string | null | undefined): boolean {
  if (email == null || typeof email !== 'string') return false
  return email.trim().toLowerCase() === INTERNAL_DEV_TOOLS_EMAIL.toLowerCase()
}
