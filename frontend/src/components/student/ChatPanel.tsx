import { FormEvent, useRef, useEffect } from 'react'
import type { ChatMessage } from '@/stores/lectureStore'

interface ChatPanelProps {
  messages: ChatMessage[]
  input: string
  onInputChange: (value: string) => void
  onSubmit: () => void
  isConnected: boolean
}

function ChatPanel({ messages, input, onInputChange, onSubmit, isConnected }: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages.length])

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (input.trim()) {
      onSubmit()
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3"
      >
        {messages.length === 0 ? (
          <div className="text-center text-2xl text-onSurface/60 mt-8">
            No messages yet
          </div>
        ) : (
          messages.map((msg) => (
            <div key={msg.id}>
              <div className="flex items-center gap-1.5 mb-0.5">
                {msg.sender === 'lecturer' && (
                  <svg
                    className="w-4 h-4 text-lecturerAccent flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.7}
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5" />
                  </svg>
                )}
                <span
                  className={`text-2xl font-semibold ${
                    msg.sender === 'lecturer' ? 'text-lecturerAccent' : 'text-onSurface'
                  }`}
                >
                  {msg.name}
                </span>
                {msg.sender === 'lecturer' && (
                  <span className="text-xl px-3 py-1 bg-lecturerAccent/15 text-lecturerAccent rounded font-medium">
                    Lecturer
                  </span>
                )}
              </div>
              <p
                className={`text-2xl leading-relaxed break-words ${
                  msg.sender === 'lecturer'
                    ? 'text-lecturerAccent/95'
                    : 'text-onSurface/90'
                }`}
              >
                {msg.text}
              </p>
            </div>
          ))
        )}
      </div>

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        className="p-5 border-t border-primaryContainer flex gap-4 shrink-0"
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={isConnected ? 'Type a message...' : 'Connecting...'}
          disabled={!isConnected}
          className="flex-1 bg-white text-gray-900 placeholder-gray-400 rounded-xl px-6 py-5 text-2xl focus:outline-none focus:ring-2 focus:ring-onPrimary disabled:opacity-60"
          maxLength={200}
        />
        <button
          type="submit"
          disabled={!input.trim() || !isConnected}
          className="px-8 py-5 bg-primary hover:opacity-90 disabled:opacity-40 text-onPrimary rounded-xl text-2xl font-medium transition-opacity"
        >
          Send
        </button>
      </form>
    </div>
  )
}

export default ChatPanel
