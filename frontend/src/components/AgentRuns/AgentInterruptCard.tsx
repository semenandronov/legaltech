export function AgentInterruptCard({
  onApprove,
  onReject,
}: {
  onApprove: () => void
  onReject: () => void
}) {
  return (
    <div
      className="mb-4 rounded-xl border p-4"
      style={{
        borderColor: 'color-mix(in srgb, var(--color-warning) 28%, var(--color-border))',
        backgroundColor: 'var(--color-bg-secondary)',
      }}
    >
      <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
        Требуется подтверждение
      </p>
      <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
        Агент готов выполнить следующий шаг. Продолжить или отменить?
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onApprove}
          className="px-3 py-1.5 rounded-lg text-xs font-medium text-white"
          style={{ backgroundColor: 'var(--color-text-primary)' }}
        >
          Продолжить
        </button>
        <button
          type="button"
          onClick={onReject}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
        >
          Отклонить
        </button>
      </div>
    </div>
  )
}
