import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Markdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import './style.css'

const api = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const examples = ['Explain how a rainbow forms', 'Help me plan a weekend trip', 'Give me a quick writing exercise']
const markdownComponents = {
  table: ({ node: _node, ...props }) => <div className="reply-table"><table {...props} /></div>,
}

function Reply({ text, metadata }) {
  return <article className="reply" data-testid="assistant-message">
    <strong>Assistant</strong>
    <div className="reply-text">
      <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={markdownComponents} skipHtml disallowedElements={['img']}>
        {text}
      </Markdown>
    </div>
    <dl>
      <div><dt>Source</dt><dd data-testid="meta-source">{metadata.resolution_source}</dd></div>
      <div><dt>Model</dt><dd data-testid="meta-model">{metadata.model}</dd></div>
      <div><dt>Latency</dt><dd data-testid="meta-latency">{metadata.latency_ms} ms</dd></div>
      <div><dt>Input tokens</dt><dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd></div>
      <div><dt>Output tokens</dt><dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd></div>
    </dl>
  </article>
}

function Chat() {
  const [session] = useState(() => globalThis.crypto?.randomUUID?.() ||
    Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join(''))
  const [draft, setDraft] = useState('')
  const [turns, setTurns] = useState([])
  const [pending, setPending] = useState(false)
  const input = useRef(null)
  const end = useRef(null)
  const sending = useRef(false)

  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [turns, pending])

  async function send(event) {
    event.preventDefault()
    const message = draft.trim()
    if (!message || sending.current) return
    sending.current = true
    setPending(true)
    setDraft('')
    setTurns(previous => [...previous, { message }])
    let outcome
    try {
      const response = await fetch(api + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session, message }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        const error = response.status === 503
          ? 'The AI providers are temporarily unavailable. Try again in a moment.'
          : typeof body.detail === 'string' ? body.detail : 'The message could not be sent. Check your input and try again.'
        outcome = { error }
      } else {
        outcome = await response.json()
      }
    } catch {
      outcome = { error: 'Could not reach the chat service. Check your connection and try again.' }
    } finally {
      setTurns(previous => [...previous.slice(0, -1), { message, ...outcome }])
      sending.current = false
      setPending(false)
      input.current?.focus()
    }
  }

  return <main>
    <header><span className="mark" aria-hidden="true">✦</span><span>Lyftr Chat</span></header>
    <section className="conversation" aria-label="Conversation" aria-live="polite">
      {!turns.length && <div className="welcome">
        <h1>What’s on your mind?</h1>
        <div className="examples">{examples.map(example => <button key={example} type="button" onClick={() => {
          setDraft(example)
          input.current?.focus()
        }}>{example}</button>)}</div>
      </div>}
      {turns.map(({ message, reply, metadata, error }, index) => <div className="turn" key={index}>
        <p className="user">{message}</p>
        {reply && <Reply text={reply} metadata={metadata} />}
        {error && <div className="error" role="alert">{error} <button type="button" onClick={() => {
          setDraft(message)
          input.current?.focus()
        }}>Restore message</button></div>}
      </div>)}
      {pending && <p className="pending" role="status">Waiting for a reply…</p>}
      <div ref={end} />
    </section>
    <form onSubmit={send}>
      <textarea ref={input} data-testid="chat-input" aria-label="Message" placeholder="Write a message…" rows="2" maxLength={4000}
        value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            event.currentTarget.form.requestSubmit()
          }
        }} />
      <button type="submit" data-testid="send-button" disabled={pending || !draft.trim()}>Send <span aria-hidden="true">↑</span></button>
    </form>
  </main>
}

createRoot(document.getElementById('root')).render(<Chat />)
