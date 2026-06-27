interface MikeUserMessageProps {
  content: string
  files?: Array<{ filename: string }>
}

/** Пузырь пользователя — копия willchen96/mike UserMessage. */
export function MikeUserMessage({ content, files }: MikeUserMessageProps) {
  const hasFiles = files && files.length > 0

  return (
    <div className="flex w-full justify-end">
      <div className="max-w-[80%] rounded-xl bg-gray-100 px-4 py-3">
        <p className="whitespace-pre-wrap text-sm text-gray-900">{content}</p>
        {hasFiles && (
          <div className="mt-3 flex flex-wrap justify-end gap-1.5">
            {files.map((file, index) => (
              <div
                key={`${file.filename}-${index}`}
                className="inline-flex items-center gap-1 rounded-[10px] border border-white/70 bg-white py-0.5 pl-2 pr-2.5 text-xs text-gray-800 shadow-[0_2px_6px_rgba(15,23,42,0.08),inset_0_1px_0_rgba(255,255,255,0.9)] backdrop-blur-xl"
              >
                <span className="max-w-[140px] truncate">{file.filename}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
